#!/usr/bin/env bash
# Setup dual EVB-LAN8670-USB on a single Raspberry Pi.
#
# Topology:
#   USB1 → eth1 (Master, PLCA Coordinator, Node ID 0, 192.168.1.1)
#   USB2 → eth2 (Slave,  PLCA Follower,    Node ID 1, 192.168.1.2)
#   Both connected via UTP cable on 10BASE-T1S multidrop bus.
#
# Usage: sudo ./setup_dual_evb.sh [master_iface] [slave_iface]
set -euo pipefail

MASTER_IFACE="${1:-eth1}"
SLAVE_IFACE="${2:-eth2}"
MASTER_IP="192.168.1.1/24"
SLAVE_IP="192.168.1.2/24"
NODE_CNT=2
TO_TIMER=50

echo "============================================"
echo "  Dual EVB-LAN8670-USB Setup (Single RPi)"
echo "============================================"
echo ""
echo "  Master: $MASTER_IFACE → $MASTER_IP (PLCA ID 0, Coordinator)"
echo "  Slave:  $SLAVE_IFACE  → $SLAVE_IP  (PLCA ID 1, Follower)"
echo "  Nodes:  $NODE_CNT"
echo ""

# --- Step 1: Detect both interfaces ---
echo "[1/5] Detecting interfaces..."
for IFACE in "$MASTER_IFACE" "$SLAVE_IFACE"; do
    if ! ip link show "$IFACE" &>/dev/null; then
        echo "ERROR: $IFACE not found."
        echo ""
        echo "Available interfaces:"
        ip -o link show | awk -F': ' '{print "  " $2}'
        echo ""
        echo "Tip: Check USB connections: lsusb | grep -i microchip"
        exit 1
    fi
    DRIVER=$(ethtool -i "$IFACE" 2>/dev/null | grep driver | awk '{print $2}' || echo "?")
    echo "  $IFACE: driver=$DRIVER ✓"
done

# --- Step 2: Configure PLCA ---
echo ""
echo "[2/5] Configuring PLCA..."

# Master = Coordinator (Node ID 0)
echo "  $MASTER_IFACE → Coordinator (Node ID 0)"
sudo ethtool --set-plca-cfg "$MASTER_IFACE" \
    enable on node-id 0 node-cnt "$NODE_CNT" to-timer "$TO_TIMER"

# Slave = Follower (Node ID 1)
echo "  $SLAVE_IFACE  → Follower (Node ID 1)"
sudo ethtool --set-plca-cfg "$SLAVE_IFACE" \
    enable on node-id 1 node-cnt "$NODE_CNT" to-timer "$TO_TIMER"

# --- Step 3: Configure IP addresses ---
echo ""
echo "[3/5] Configuring IP addresses..."

for IFACE in "$MASTER_IFACE" "$SLAVE_IFACE"; do
    sudo ip addr flush dev "$IFACE" 2>/dev/null || true
done

sudo ip addr add "$MASTER_IP" dev "$MASTER_IFACE"
sudo ip link set "$MASTER_IFACE" up
echo "  $MASTER_IFACE → $MASTER_IP ✓"

sudo ip addr add "$SLAVE_IP" dev "$SLAVE_IFACE"
sudo ip link set "$SLAVE_IFACE" up
echo "  $SLAVE_IFACE  → $SLAVE_IP ✓"

# --- Step 4: Verify PLCA beacon ---
echo ""
echo "[4/5] Waiting for PLCA beacon..."
sleep 2

echo "  Master ($MASTER_IFACE) PLCA status:"
ethtool --get-plca-status "$MASTER_IFACE" 2>/dev/null | sed 's/^/    /' || echo "    (unavailable)"

echo "  Slave ($SLAVE_IFACE) PLCA status:"
ethtool --get-plca-status "$SLAVE_IFACE" 2>/dev/null | sed 's/^/    /' || echo "    (unavailable)"

# --- Step 5: Connectivity test ---
echo ""
echo "[5/5] Testing connectivity..."
if ping -c 2 -W 2 -I "$MASTER_IFACE" 192.168.1.2 &>/dev/null; then
    echo "  ping 192.168.1.1 → 192.168.1.2: ✓ OK"
else
    echo "  ping 192.168.1.1 → 192.168.1.2: ✗ FAILED"
    echo "  (PLCA may need a few seconds to stabilize)"
fi

if ping -c 2 -W 2 -I "$SLAVE_IFACE" 192.168.1.1 &>/dev/null; then
    echo "  ping 192.168.1.2 → 192.168.1.1: ✓ OK"
else
    echo "  ping 192.168.1.2 → 192.168.1.1: ✗ FAILED"
fi

echo ""
echo "============================================"
echo "  Setup Complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Start zenohd on master interface:"
echo "     zenohd --listen tcp/192.168.1.1:7447"
echo ""
echo "  2. Run hardware bypass test:"
echo "     python3 -m pytest tests/test_hw_bypass.py -v"
echo ""
echo "  3. Or run full master + slave:"
echo "     Terminal 1: zenoh-t1s-master start --interface $MASTER_IFACE"
echo "     Terminal 2: python3 tests/test_hw_bypass.py --slave $SLAVE_IFACE"
