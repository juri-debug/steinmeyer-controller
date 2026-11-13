#!/usr/bin/env bash
# Vergibt dem Galil-Controller (MAC 00:50:4c:00:28:52) per BOOTP die feste IP
# 192.168.0.100 auf der Netzwerkkarte eno2. Muss nach JEDEM Einschalten des
# Controllers einmal laufen, da er keine IP im EEPROM speichert.
#
# Voraussetzungen (einmalig, siehe Anleitung PDF):
#   - eno2 hat eine statische IP im selben Subnetz (z.B. 192.168.0.1/24)
#   - Firewall erlaubt eingehendes UDP/67 auf eno2 (ggf. kurz stoppen)
#
# Aufruf: sudo bash assign_controller_ip.sh

set -euo pipefail

IFACE="eno2"
CONTROLLER_MAC="00:50:4c:00:28:52"
IP_RANGE_START="192.168.0.100"
IP_RANGE_END="192.168.0.110"
NETMASK="255.255.255.0"

DNSMASQ=$(nix shell nixpkgs#dnsmasq -c which dnsmasq)

exec timeout 90 "$DNSMASQ" \
  --conf-file=/dev/null \
  --no-daemon \
  --port=0 \
  --interface="$IFACE" \
  --bind-interfaces \
  --dhcp-range="$IP_RANGE_START,$IP_RANGE_END,$NETMASK,1h" \
  --dhcp-host="$CONTROLLER_MAC,$IP_RANGE_START" \
  --log-dhcp
