#!/usr/bin/env bash
# Firecracker microVM networking setup — RUN ONCE AS ROOT (sudo).
#
# Creates an isolated host bridge + a pool of persistent TAP devices owned by your user. The
# Peakstone harness then *attaches* Firecracker VMs to these taps, which (because they already exist
# and you own them) needs NO CAP_NET_ADMIN at runtime. The bridge has NO uplink and NO NAT, so guest
# microVMs have no internet — that is the `egress=blocked` condition, for real.
#
# These devices are runtime-only and do NOT survive a reboot. To persist, install the systemd unit
# this script prints at the end (or re-run after boot).
#
#   sudo ./fc-net-setup.sh            # create
#   sudo ./fc-net-setup.sh --down     # remove
set -euo pipefail

# The taps must be owned by the (non-root) user who runs the harness — Firecracker can only open a
# pre-existing tap without CAP_NET_ADMIN if that uid owns it. Under `sudo` SUDO_USER is right; under
# systemd there is no SUDO_USER, so the unit must pass PEAKSTONE_FC_TAP_USER explicitly (the unit
# printed below does — a unit without it silently creates a root-owned pool and every networked
# microVM boot dies with EPERM).
USER_NAME="${PEAKSTONE_FC_TAP_USER:-${SUDO_USER:-$USER}}"
BR="${PEAKSTONE_FC_BRIDGE:-psfc-br0}"
PREFIX="${PEAKSTONE_FC_TAP_PREFIX:-psfc-tap}"
SUBNET="${PEAKSTONE_FC_SUBNET:-172.30.0}"
COUNT="${PEAKSTONE_FC_TAP_COUNT:-8}"

if [ "$(id -u)" != "0" ]; then echo "run as root (sudo)"; exit 1; fi

if [ "${1:-}" = "--down" ]; then
  for i in $(seq 0 $((COUNT-1))); do ip link del "${PREFIX}${i}" 2>/dev/null || true; done
  ip link del "$BR" 2>/dev/null || true
  echo "removed $BR and ${PREFIX}0..$((COUNT-1))"
  exit 0
fi

if ! WANT_UID="$(id -u "$USER_NAME" 2>/dev/null)" || [ "$WANT_UID" = "0" ]; then
  echo "refusing to create a root-owned tap pool (resolved owner: '$USER_NAME')." >&2
  echo "set PEAKSTONE_FC_TAP_USER=<the user that runs the harness> and re-run." >&2
  exit 1
fi

ip link show "$BR" >/dev/null 2>&1 || ip link add "$BR" type bridge
ip addr replace "${SUBNET}.1/24" dev "$BR"
ip link set "$BR" up
for i in $(seq 0 $((COUNT-1))); do
  TAP="${PREFIX}${i}"
  # repair a wrong-owner tap (e.g. a root-owned pool from a unit without PEAKSTONE_FC_TAP_USER):
  # tun ownership is fixed at creation (TUNSETOWNER), so delete + recreate
  if [ -e "/sys/class/net/$TAP" ] && [ "$(cat "/sys/class/net/$TAP/owner" 2>/dev/null)" != "$WANT_UID" ]; then
    ip link del "$TAP"
  fi
  ip link show "$TAP" >/dev/null 2>&1 || ip tuntap add dev "$TAP" mode tap user "$USER_NAME"
  ip link set "$TAP" master "$BR"
  ip link set "$TAP" up
done
# deliberately NO `sysctl net.ipv4.ip_forward` and NO NAT — keep guests off the internet.

echo "OK: bridge '$BR' (${SUBNET}.1/24) + ${COUNT} taps '${PREFIX}0..$((COUNT-1))' owned by '$USER_NAME', no uplink."
cat <<EOF

To persist across reboots, install a systemd unit:

  sudo tee /etc/systemd/system/peakstone-fcnet.service >/dev/null <<UNIT
  [Unit]
  Description=Peakstone Firecracker microVM network (bridge + tap pool)
  After=network-pre.target
  [Service]
  Type=oneshot
  RemainAfterExit=yes
  Environment=PEAKSTONE_FC_TAP_COUNT=${COUNT}
  Environment=PEAKSTONE_FC_TAP_USER=${USER_NAME}
  ExecStart=$(readlink -f "$0")
  ExecStop=$(readlink -f "$0") --down
  [Install]
  WantedBy=multi-user.target
  UNIT
  sudo systemctl enable --now peakstone-fcnet.service
EOF
