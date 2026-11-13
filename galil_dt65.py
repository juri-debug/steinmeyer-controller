#!/usr/bin/env python3
"""
Ansteuerung der Steinmeyer DT65-NM (Nanomotion-Piezomotor, Achse A) ueber einen
Galil-Motion-Controller (Seriennummer 10322) per Ethernet/Telnet (Port 23).

Kalibrierung (gemessen ueber 10 exakt gezaehlte volle Umdrehungen):
  4064288 Counts / 10 Umdrehungen = 406428.8 Counts / Umdrehung
                                  = 1128.97 Counts / Grad
Deutlich verlaesslicher als eine Bruchteils-Schaetzung, da sich der
Zaehlfehler (+/- 1 Umdrehung) auf 10 Umdrehungen verteilt (~10% statt ggf.
50%+ Fehler). Bei Bedarf mit mehr Umdrehungen weiter verfeinern.

Der Controller hat keine im EEPROM gespeicherte IP (BOOTP-Client ohne Server-
Antwort noetig vor jeder Sitzung, siehe dnsmasq_test.sh im scratchpad).
"""

import socket
import time

COUNTS_PER_REV = 406428.8
COUNTS_PER_DEG = COUNTS_PER_REV / 360.0

DEFAULT_IP = "192.168.0.100"
DEFAULT_PORT = 23
AXIS = "A"


class GalilError(RuntimeError):
    pass


class DT65:
    def __init__(self, ip=DEFAULT_IP, port=DEFAULT_PORT, axis=AXIS, timeout=3.0):
        self.axis = axis
        self.sock = socket.create_connection((ip, port), timeout=timeout)
        self.sock.settimeout(timeout)

    def close(self):
        self.sock.close()

    def _cmd(self, c, wait=0.3):
        self.sock.sendall((c + "\r").encode("ascii"))
        time.sleep(wait)
        try:
            resp = self.sock.recv(8192).decode("ascii", "replace")
        except socket.timeout:
            resp = ""
        return resp.strip()

    def _check(self):
        resp = self._cmd("TC1").strip(":").strip()
        code = resp.split()[0] if resp.split() else resp
        if code != "0":
            raise GalilError(f"Galil-Fehler: {resp!r}")

    def position_counts(self):
        resp = self._cmd("TP")
        values = [float(x) for x in resp.strip(":").split(",")]
        axis_index = ord(self.axis) - ord("A")
        return values[axis_index]

    def position_deg(self):
        return self.position_counts() / COUNTS_PER_DEG

    def servo_on(self):
        self._cmd(f"SH{self.axis}")
        self._check()

    def motor_off(self, retries=10, retry_wait=0.3):
        """Motor ausschalten. Direkt nach STA kann der Controller das kurz
        mit Fehler 7 ('Command not valid while running') ablehnen, solange
        die Abbremsrampe noch nicht ganz fertig ist -> einfach erneut versuchen."""
        for _ in range(retries):
            self._cmd(f"MO{self.axis}")
            resp = self._cmd("TC1").strip(":").strip()
            if resp.split()[0] == "0":
                return
            time.sleep(retry_wait)
        raise GalilError(f"MO{self.axis} fehlgeschlagen: {resp!r}")

    def stop(self):
        self._cmd(f"ST{self.axis}")

    def _wait_motion_complete(self, poll=0.1, max_wait=30.0):
        start = time.time()
        while time.time() - start < max_wait:
            resp = self._cmd(f"MG _BG{self.axis}", wait=poll)
            if resp.strip(":").strip() == "0.0000":
                return
            time.sleep(poll)

    def move_relative_deg(self, degrees, disable_after=True):
        counts = round(degrees * COUNTS_PER_DEG)
        self.servo_on()
        self._cmd(f"PR{self.axis}={counts}")
        self._check()
        self._cmd(f"BG{self.axis}")
        self._check()
        self._wait_motion_complete()
        self.stop()
        if disable_after:
            time.sleep(0.3)
            self.motor_off()

    def move_absolute_deg(self, degrees, disable_after=True):
        current = self.position_deg()
        self.move_relative_deg(degrees - current, disable_after=disable_after)

    def zero_here(self):
        """Aktuelle physische Ausrichtung als 0 Grad definieren (Referenzpunkt
        fuer move_absolute_deg). Motor sollte dabei ausgeschaltet/stillstehend
        sein. Nur einmal nach dem Ausrichten der Stage aufrufen - geht beim
        naechsten Stromzyklus des Controllers wieder verloren."""
        self._cmd(f"DP{self.axis}=0")
        self._check()

    def send_raw(self, command):
        """Beliebigen Galil-Befehl senden, Rohantwort zurueckgeben (fuer Diagnose)."""
        return self._cmd(command)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Steinmeyer DT65 (Achse A) per Galil ansteuern")
    ap.add_argument("--ip", default=DEFAULT_IP)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--rel", type=float, metavar="GRAD", help="relative Bewegung um GRAD Grad")
    group.add_argument("--abs", type=float, metavar="GRAD", help="absolute Bewegung auf GRAD Grad")
    group.add_argument("--status", action="store_true", help="nur aktuelle Position anzeigen")
    group.add_argument("--zero", action="store_true", help="aktuelle Ausrichtung als 0 Grad festlegen")
    group.add_argument("--raw", metavar="BEFEHL", help="rohen Galil-Befehl senden (Diagnose)")
    args = ap.parse_args()

    with DT65(ip=args.ip, port=args.port) as dt:
        if args.raw is not None:
            print(dt.send_raw(args.raw))
        elif args.zero:
            dt.zero_here()
            print("0 Grad auf aktuelle Position gesetzt.")
        elif args.status:
            print(f"Position: {dt.position_deg():.3f} deg ({dt.position_counts():.0f} counts)")
        elif args.abs is not None:
            print("vorher:", round(dt.position_deg(), 3), "deg")
            dt.move_absolute_deg(args.abs)
            print("nachher:", round(dt.position_deg(), 3), "deg")
        else:
            angle = args.rel if args.rel is not None else 10.0
            print("vorher:", round(dt.position_deg(), 3), "deg")
            dt.move_relative_deg(angle)
            print("nachher:", round(dt.position_deg(), 3), "deg")
