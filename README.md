# steinmeyer-controller

Python-Steuerung für die **Steinmeyer DT65-NM** Rotationsstage
(Nanomotion-HR2-Piezomotor, Achse A) über einen bislang unlabeled **Galil
Motion Controller** (SN 10322), per Ethernet direkt am Rechner.

Details zu Hardware-Identifikation, Netzwerk-Setup, Protokoll, Kalibrierung
und Sicherheitshinweisen: siehe [`manual.pdf`](manual.pdf) / `manual.md`.

## Quickstart

```bash
# nach jedem Einschalten des Controllers einmalig (vergibt die IP per BOOTP)
sudo bash assign_controller_ip.sh

# Status / Position
python3 galil_dt65.py --status

# aktuelle Ausrichtung als 0 Grad festlegen (fuer absolute Bewegungen)
python3 galil_dt65.py --zero

# bewegen
python3 galil_dt65.py --rel 45     # relativ um 45 Grad
python3 galil_dt65.py --abs 90     # absolut auf 90 Grad
```

## Dateien

| Datei                    | Zweck                                              |
|---------------------------|-----------------------------------------------------|
| `galil_dt65.py`           | Python-Modul + CLI zur Steuerung von Achse A        |
| `assign_controller_ip.sh` | BOOTP-IP-Vergabe nach jedem Einschalten             |
| `manual.md` / `manual.pdf`| Vollständige Anleitung                               |
| `fmc_probe.py`            | Protokoll-Diagnose-Skript (fuer unbekannte Achsen/Dialekte) |
