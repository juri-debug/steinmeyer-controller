---
title: "Steinmeyer DT65-NM über Galil-Controller – Anleitung"
author: ""
date: "2026-11-13"
---

# Überblick

Die Rotationsstage **Steinmeyer DT65-NM** (Nanomotion-HR2-Piezomotor) hängt an
**Achse A** eines älteren **Galil-Motion-Controllers** (Gehäuse-Etikett
"030504-G", 5 Achsmodule A–E, Seriennummer **10322**, ermittelt über
`MG _BN`). Die Identifikation als Galil-Gerät erfolgte zweifelsfrei über:

- den MAC-OUI `00:50:4C` der Ethernet-Karte (registriert auf Galil Motion
  Control),
- das klassische Galil-Antwortprotokoll (`:` = OK, `?` = Fehler, `TCx` =
  Fehlertext),
- die Variable `_BN` (Seriennummer).

Der Controller wird direkt per LAN-Kabel (kein Switch) mit dem Laptop
verbunden, Ethernet-Port "Ethernet" am Kommunikationsmodul.

---

# 1. Besonderheit: Keine gespeicherte IP

Dieser Controller hat **keine IP-Adresse im EEPROM gespeichert**. Beim
Einschalten sendet er alle ~5 Sekunden einen BOOTP-Request
(`0.0.0.0:68 → 255.255.255.255:67`) von seiner MAC-Adresse
`00:50:4c:00:28:52` und wartet auf eine Antwort. Ohne Antwort bekommt er
nie eine IP, und er ist dann über **kein** Subnetz per ARP/Ping erreichbar.

**Konsequenz:** Nach jedem Aus-/Einschalten des Controllers muss einmal ein
minimaler BOOTP/DHCP-Server auf dem Laptop laufen, der ihm gezielt (über
seine MAC-Adresse) die IP `192.168.0.100` zuweist.

## Einmalige Einrichtung der Netzwerkkarte

Die Ethernet-Schnittstelle am Laptop (hier: `eno2`) braucht eine feste IP im
selben Subnetz, z. B. per NetworkManager:

```bash
nmcli connection add type ethernet ifname eno2 con-name probe-static \
  ipv4.method manual ipv4.addresses 192.168.0.1/24 ipv6.method ignore
nmcli connection up probe-static
```

Das muss nur einmal eingerichtet werden; danach bleibt die Verbindung
bestehen (ggf. beim Systemstart automatisch aktiv, je nach NetworkManager-
Konfiguration).

## IP-Zuweisung nach jedem Einschalten

Dazu dient das Skript `assign_controller_ip.sh` (im Projektordner). Es startet
`dnsmasq` als einmaligen BOOTP-Responder, ausschließlich auf `eno2`, und
vergibt **nur** der bekannten MAC-Adresse des Controllers die IP
`192.168.0.100`.

```bash
sudo bash assign_controller_ip.sh
```

- Muss **nach** dem Einschalten des Controllers laufen (BOOTP-Requests
  kommen nur kurz nach dem Boot in einem Zeitfenster von ca. 20–30 s – im
  Zweifel das Skript zuerst starten, danach den Controller einschalten).
- Läuft 90 Sekunden und beendet sich automatisch.
- Braucht `sudo` **mit echtem Terminal** (ein Passwort-Prompt ohne TTY, z. B.
  über manche Automatisierungs-/Chat-Shells, funktioniert nicht –
  `pkexec` war auf diesem System ebenfalls nicht nutzbar, da nicht korrekt
  als `setuid root` installiert).
- Falls die lokale Firewall aktiv ist und eingehendes UDP/67 blockt, vorher
  kurz stoppen:
  ```bash
  sudo systemctl stop firewall
  # ... assign_controller_ip.sh laufen lassen ...
  sudo systemctl start firewall   # danach wieder aktivieren
  ```
  (Systemd-Unit-Name hier: `firewall.service`, NixOS-spezifisch.)

Danach ist der Controller unter `192.168.0.100` erreichbar, bis er das
nächste Mal ausgeschaltet wird.

---

# 2. Kommunikationsprotokoll (Galil-Standard)

- TCP, Port **23** (im unkonfigurierten Zustand akzeptiert der Controller
  Verbindungen auf praktisch jedem Port identisch – offenbar ein
  Bootstrap-/Minimal-Stack ohne Port-Unterscheidung; für den Normalbetrieb
  **immer Port 23 verwenden**).
- Zeilenende: `\r` (CR). Antworten enden mit `\r\n` + `:` (Erfolg) oder nur
  `?` (Fehler).
- Fehlertext abfragen: `TC1` → z. B. `9 Variable error`, `20 Begin not valid
  with motor off`.
- Positionsabfrage: `TP` → kommagetrennte Liste, ein Wert pro Achse (A,B,C,D,E).

## Wichtige Befehle (Achse A als Beispiel)

| Befehl         | Bedeutung                                      |
|----------------|-------------------------------------------------|
| `SHA`          | Servo/Motor an Achse A einschalten              |
| `MOA`          | Motor an Achse A **komplett ausschalten**       |
| `STA`          | Bewegung an Achse A stoppen (Abbremsrampe)      |
| `PRA=<counts>` | Relative Zielposition in Encoder-Counts setzen  |
| `BGA`          | Bewegung starten ("Begin")                      |
| `JGA=<c/s>`    | Jog-Geschwindigkeit setzen (Counts/Sekunde)     |
| `TP`           | Aktuelle Position aller Achsen (Counts)         |
| `MG _BGA`      | 0 = Bewegung fertig, 1 = Bewegung läuft         |
| `MG _MOA`      | 0 = Motor an, 1 = Motor aus                     |
| `MG _BN`       | Seriennummer des Controllers                    |
| `TC1`          | Letzter Fehlercode + Klartext                   |

## Unbedingt vermeiden

- **`BN`** (Burn to EEPROM) – schreibt Parameter dauerhaft. Nicht senden,
  solange der Inhalt des EEPROMs nicht bekannt/gesichert ist.
- **`DL`** (Download/Programmiermodus) – öffnet einen Editor-Modus, der
  nachfolgende Zeilen stillschweigend als Programmcode einliest statt sie
  auszuführen. Ist uns einmal passiert (`LS`, `TPA` etc. wurden dadurch
  "verschluckt"). Beendet sich mit einer Zeile, die nur `\` enthält.
  **Lesen des gespeicherten Programms stattdessen mit `LS` (ohne
  vorheriges `DL`).**

---

# 3. Python-Modul `galil_dt65.py`

Das Modul im Projektordner stellt eine Klasse `DT65` sowie ein CLI bereit.

## Als Bibliothek

```python
from galil_dt65 import DT65

with DT65() as dt:          # verbindet zu 192.168.0.100:23, Achse A
    print(dt.position_deg())      # aktuelle Position in Grad
    dt.move_relative_deg(10)      # 10 Grad weiterdrehen
    dt.move_absolute_deg(90)      # auf 90 Grad (relativ zur aktuellen Zaehlung) fahren
```

Jede `move_*`-Methode schaltet den Motor am Ende automatisch wieder aus
(`disable_after=True`, Standard), um das kurze Brummen in der Haltephase
nicht dauerhaft laufen zu lassen.

## Als Kommandozeilen-Tool

```bash
python3 galil_dt65.py --status            # nur Position anzeigen
python3 galil_dt65.py --zero              # aktuelle Ausrichtung = 0 Grad festlegen
python3 galil_dt65.py --rel 10            # 10 Grad relativ drehen
python3 galil_dt65.py --abs 90            # auf 90 Grad (absolut, relativ zu --zero) drehen
python3 galil_dt65.py --raw "TC1"         # beliebigen Rohbefehl senden (Diagnose)
```

---

# 4. Kalibrierung

Gemessen wurde eine Bewegung über **exakt 10 gezählte volle Umdrehungen**,
Encoder-Differenz 4064288 Counts:

```
Counts pro Umdrehung = 4064288 / 10 = 406428.8
Counts pro Grad       = 406428.8 / 360 ≈ 1128.97
```

Diese Werte stehen als `COUNTS_PER_REV` am Kopf von `galil_dt65.py` und
werden für alle Grad-Umrechnungen verwendet. Durch die Verteilung auf 10
Umdrehungen liegt der Schätzfehler (±1 gezählte Umdrehung) bei grob ±10%
statt wie bei einer Bruchteils-Schätzung schnell bei 50%+. Für noch mehr
Genauigkeit: dieselbe Messung mit mehr Umdrehungen (z. B. 20–30) wiederholen
und `COUNTS_PER_REV` entsprechend aktualisieren.

Ein `FI`-Befehl (Find Index, Encoder-Nullpuls) wurde ebenfalls getestet und
funktioniert, ist aber für die Counts/Umdrehung-Messung ungeeignet: Der
Controller setzt die Position beim Erreichen des Index automatisch auf 0
zurück, wodurch eine Vorher/Nachher-Messung über `TP` verzerrt wird. Nützlich
ist `FI` aber als **physische Referenzfahrt** (siehe Abschnitt 5).

## Genauigkeit für 0–90°-Anwendungen: Nullpunkt-Referenz nötig

`galil_dt65.py` zählt Grad einfach als `Counts / COUNTS_PER_REV`, bezogen auf
den Zählerstand, der zufällig beim ersten Verbindungsaufbau vorlag – das hat
**keinen Bezug zur echten Ausrichtung** der Stage. Für einen definierten
Bereich 0–90° muss einmalig eine physische "0°"-Position festgelegt werden:

```bash
# Stage manuell/per Befehl auf die gewuenschte 0 Grad Ausrichtung bringen,
# Motor steht (kein SH aktiv), dann:
python3 galil_dt65.py --zero
```

Das setzt den Encoderzaehler per Galil-Befehl `DPA=0` auf die aktuelle
Position. **Diese Referenz geht beim nächsten Stromzyklus des Controllers
verloren** (Encoderzähler ist flüchtig) und muss nach jedem Neustart einmal
neu gesetzt werden, bevor mit `--abs`/`move_absolute_deg()` gearbeitet wird.

---

# 5. Beobachtetes Verhalten / Sicherheitshinweise

- **Encoder-Kabel:** Zu Beginn lieferte `TP` durchgehend `0` – der Motor
  bewegte sich nachweislich trotzdem (Jog-Test über mehrere Sekunden war
  hör- und spürbar). Nach Tausch/Neuanschluss des Encoder-Kabels an Achse A
  hat `TP` korrekt mitgezählt. **Bei anderen Achsen (B–E) wurde das noch
  nicht geprüft.**
- **Brummen/Vibrieren:** Ein kurzes, niederfrequentes Brummen kurz vor dem
  automatischen Abschalten (`STA` + `MOA`) scheint für diesen
  Piezo-Antrieb normal zu sein (Nachregeln des Servos in der Stopp-Phase).
  Ein **lautes, anhaltendes** Brummen ohne nennenswerte Drehung (so
  geschehen, als der Motor nach einem Test längere Zeit mit `SHA` aktiv
  blieb, ohne eine neue Bewegung zu bekommen) deutet auf ein Problem hin
  (z. B. Servo hält Position durch Dauer-Nachregeln) – in diesem Fall
  sofort `MOA` senden bzw. den Controller ausschalten.
- **Deshalb:** Motor nur unmittelbar vor einer Bewegung einschalten
  (`SHA`) und direkt danach wieder ausschalten (`MOA`) – genau das macht
  `galil_dt65.py` automatisch.
- **Nicht getestet:** Achsen B, C, D, E (mechanisch evtl. gar nicht
  bestückt), absolute Nullposition/Referenzierung (Home), Limit-Schalter
  (beide lesen denselben Wert – vermutlich nicht verdrahtet, da die DT65
  eine Endlos-Rotationsachse ist).

---

# 6. Dateien im Projekt

| Datei                      | Zweck                                             |
|-----------------------------|----------------------------------------------------|
| `galil_dt65.py`             | Python-Modul + CLI zur Steuerung von Achse A       |
| `assign_controller_ip.sh`   | Vergibt dem Controller nach dem Einschalten die IP |
| `fmc_probe.py`               | Allgemeines Diagnose-/Brute-Force-Skript (Ethernet)|
| `manual.md` / `manual.pdf`  | Dieses Dokument                                     |

## Typischer Ablauf einer Sitzung

```bash
# 1) Controller einschalten
# 2) IP zuweisen (einmalig pro Einschaltvorgang)
sudo bash assign_controller_ip.sh
# 3) Status pruefen
python3 galil_dt65.py --status
# 4) Bewegen
python3 galil_dt65.py --rel 15
```
