#!/usr/bin/env python3
"""
fmc_probe.py - Brute-force-Sonde fuer einen Motion-Controller mit Ethernet
(z. B. Steinmeyer FMC400) ohne bekanntes Protokoll.

Ablauf:
  1. Portscan auf der Controller-IP (oder --port vorgeben)
  2. Banner lesen, Zeilenenden + Abfragebefehle testen -> welche Antworten kommen?
  3. Bewegungs-Sequenzen aus vielen gaengigen Dialekten durchprobieren
     (G-Code, PI-GCS, Galil, Newport, OWIS-artig, generisch ...).
     Nach jeder Sequenz: Positions-Abfragen vergleichen und (optional) dich fragen,
     ob sich die Stage gedreht hat.

Alles wird in fmc_probe_log.txt mitgeschrieben.

Beispiele:
  python3 fmc_probe.py 192.168.0.10
  python3 fmc_probe.py 192.168.0.10 --port 5000
  python3 fmc_probe.py 192.168.0.10 --auto      # nicht nachfragen, nur Positionsvergleich
"""

import argparse
import re
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor

LOG = open("fmc_probe_log.txt", "a", encoding="utf-8")


def log(msg=""):
    print(msg)
    LOG.write(msg + "\n")
    LOG.flush()


# ---------------------------------------------------------------- Portscan
COMMON_PORTS = [23, 80, 502, 1000, 2000, 3000, 4000, 4001, 5000, 5001, 5025,
                7000, 8000, 8080, 9000, 10000, 10001, 23000, 50000, 50001, 50002]


def port_open(ip, port, timeout=0.4):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return port
    except OSError:
        return None


def scan(ip, full):
    ports = range(1, 65536) if full else COMMON_PORTS
    log(f"[Scan] {ip}: {'alle 65535' if full else len(COMMON_PORTS)} Ports ...")
    with ThreadPoolExecutor(max_workers=400) as ex:
        found = [p for p in ex.map(lambda p: port_open(ip, p), ports) if p]
    log(f"[Scan] offen: {found}")
    return found


# ---------------------------------------------------------------- Verbindung
class Conn:
    def __init__(self, ip, port, term, timeout=0.8):
        self.ip, self.port, self.term, self.timeout = ip, port, term, timeout
        self.sock = None

    def open(self):
        self.close()
        self.sock = socket.create_connection((self.ip, self.port), timeout=3)
        self.sock.settimeout(self.timeout)

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def read_all(self, wait=None):
        """Liest alles, was innerhalb des Timeouts kommt."""
        data = b""
        self.sock.settimeout(wait or self.timeout)
        try:
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise ConnectionError("Verbindung vom Controller geschlossen")
                data += chunk
                self.sock.settimeout(0.25)  # nach erstem Paket kurz auf Rest warten
        except socket.timeout:
            pass
        return data

    def cmd(self, c):
        if self.sock is None:
            self.open()
        try:
            self.sock.sendall((c + self.term).encode("ascii", "replace"))
            resp = self.read_all()
        except (OSError, ConnectionError) as e:
            log(f"    !! {e} -> reconnect")
            self.open()
            return None
        txt = resp.decode("ascii", "replace").strip()
        log(f"    > {c!r:40} < {txt!r}")
        return txt


# ---------------------------------------------------------------- Befehlslisten
QUERIES = ["?", "*IDN?", "ID?", "IDN?", "VER", "VER?", "VERSION", "?VER", "HELP",
           "INFO", "STATUS", "STAT?", "STA?", "ERR?", "POS?", "?POS", "TP", "MG _TPA",
           "M114", "$I", "?ASTAT", "?CNT1", "1TP", "TPA", "PA?", "RP", "AXIS?"]

AXES = ["X", "A", "C", "1", "0"]

# Sequenzen: {ax} = Achsbuchstabe/-nummer. Kleine Relativbewegungen (~10 deg bzw. Counts).
MOTION_SEQS = [
    ("G-Code relativ G1", ["G91", "G1 {ax}10 F30"]),
    ("G-Code relativ G0", ["G91", "G0 {ax}10"]),
    ("G-Code nur Achswort", ["G91", "{ax}10"]),
    ("G-Code absolut", ["G90", "G1 {ax}20 F30"]),
    ("PI GCS", ["SVO {ax} 1", "MVR {ax} 10"]),
    ("PI GCS + Referenz", ["SVO {ax} 1", "FRF {ax}", "MOV {ax} 10"]),
    ("Galil", ["SH{ax}", "PR{ax}=1000", "BG{ax}"]),
    ("Galil Jog", ["SH{ax}", "JG{ax}=1000", "BG{ax}", "WT500", "ST{ax}"]),
    ("Newport ESP/SMC", ["{ax}MO", "{ax}PR10"]),
    ("Newport ESP + OR", ["{ax}MO", "{ax}OR", "{ax}PA10"]),
    ("OWIS-artig", ["INIT{ax}", "EFREE{ax}", "RELAT{ax}", "PSET{ax}=1000", "PGO{ax}"]),
    ("Generisch ENABLE/MOVE", ["ENABLE {ax}", "MOVEREL {ax} 10"]),
    ("Generisch EN/MR", ["EN {ax}", "MR {ax} 10"]),
    ("Generisch MO/MR", ["MO {ax}=1", "MR {ax}=10"]),
    ("Generisch POWER/MOVE", ["POWER {ax} ON", "MOVE {ax} 10"]),
    ("Generisch HOME", ["HOME {ax}"]),
    ("Generisch REF", ["REF {ax}"]),
    ("Technosoft-TML-Text", ["AXISON", "CPR 1000L", "CPA", "MODE PP", "TUM1", "UPD"]),
]

NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def numbers(txt):
    return [float(x) for x in NUM_RE.findall(txt or "")]


# ---------------------------------------------------------------- Phasen
def pick_terminator(ip, port):
    """Probiert Zeilenenden, gibt das mit den 'interessantesten' Antworten zurueck."""
    best, best_score = "\r\n", -1
    for name, term in [("CRLF", "\r\n"), ("CR", "\r"), ("LF", "\n"), (";", ";")]:
        log(f"\n[Terminator {name}] Port {port}")
        c = Conn(ip, port, term)
        try:
            c.open()
            banner = c.read_all(wait=1.5).decode("ascii", "replace").strip()
            if banner:
                log(f"    Banner: {banner!r}")
            answers = {q: c.cmd(q) for q in ["?", "*IDN?", "VER", "HELP", "POS?", "TP"]}
        except OSError as e:
            log(f"    Verbindung fehlgeschlagen: {e}")
            continue
        finally:
            c.close()
        distinct = {a for a in answers.values() if a}
        score = len(distinct)
        log(f"    -> {score} verschiedene nichtleere Antworten")
        if score > best_score:
            best, best_score = term, score
    return best, best_score


def find_position_queries(c):
    """Abfragen, die Zahlen liefern -> fuer Bewegungs-Erkennung."""
    log("\n[Abfragen] Suche Befehle, die Zahlen zurueckgeben ...")
    good = []
    for q in QUERIES:
        r = c.cmd(q)
        if r and numbers(r) and r.strip() != q:
            good.append(q)
    for ax in AXES:
        for tmpl in ["POS? {ax}", "{ax}TP", "TP{ax}", "?POS {ax}", "{ax}PA?", "PFB{ax}"]:
            q = tmpl.format(ax=ax)
            r = c.cmd(q)
            if r and numbers(r) and r.strip() != q:
                good.append(q)
    log(f"[Abfragen] Zahlen-Antworten von: {good}")
    return good


def snapshot(c, queries):
    return {q: numbers(c.cmd(q)) for q in queries}


def try_motion(c, pos_queries, auto):
    log("\n[Bewegung] Probiere Bewegungs-Sequenzen ...")
    for name, seq in MOTION_SEQS:
        for ax in AXES:
            if "{ax}" not in "".join(seq) and ax != AXES[0]:
                continue  # achsunabhaengige Sequenz nur einmal
            cmds = [s.format(ax=ax) for s in seq]
            log(f"\n--- {name} | Achse {ax}: {cmds}")
            before = snapshot(c, pos_queries)
            for cmd in cmds:
                c.cmd(cmd)
            time.sleep(1.5)
            after = snapshot(c, pos_queries)
            changed = [q for q in pos_queries if before.get(q) != after.get(q)]
            if changed:
                log(f"*** Positionsabfrage hat sich geaendert: {changed}")
                log(f"    vorher {[before[q] for q in changed]} nachher {[after[q] for q in changed]}")
            moved = bool(changed)
            if not auto:
                ans = input("    Hat sich die Stage bewegt? [j/N/q] ").strip().lower()
                if ans == "q":
                    sys.exit(0)
                moved = ans == "j"
            if moved:
                log(f"\n######## TREFFER: {name}, Achse {ax}")
                log(f"######## Befehle: {cmds}")
                log(f"######## Zeilenende: {c.term!r}, Port {c.port}")
                return True
    return False


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ip")
    ap.add_argument("--port", type=int, help="Port bekannt -> kein Scan")
    ap.add_argument("--full-scan", action="store_true", help="alle 65535 Ports scannen")
    ap.add_argument("--auto", action="store_true", help="nicht nachfragen, nur Positionsvergleich")
    args = ap.parse_args()

    log(f"\n===== fmc_probe {time.strftime('%Y-%m-%d %H:%M:%S')} =====")
    ports = [args.port] if args.port else scan(args.ip, args.full_scan)
    if not ports and not args.full_scan:
        ports = scan(args.ip, True)
    if not ports:
        log("Keine offenen Ports. IP/Netz pruefen (ping, arp -a).")
        return
    if 80 in ports or 8080 in ports:
        log("Hinweis: Webserver offen -> im Browser http://%s ansehen!" % args.ip)

    for port in ports:
        if port in (80, 8080) and len(ports) > 1:
            continue
        term, score = pick_terminator(args.ip, port)
        log(f"\n[Port {port}] gewaehltes Zeilenende {term!r} (Score {score})")
        c = Conn(args.ip, port, term)
        c.open()
        pos_q = find_position_queries(c)
        if try_motion(c, pos_q, args.auto):
            c.close()
            return
        c.close()
    log("\nKein Treffer. Log (fmc_probe_log.txt) ansehen: Fehlermeldungen des Controllers "
        "verraten oft die Syntax.")


if __name__ == "__main__":
    main()