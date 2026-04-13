#!/usr/bin/env bash
# Configure PLCA Coordinator on the 10BASE-T1S interface.
# PRD Section 6, Steps 1-4.
#
# Usage: sudo ./setup_plca.sh [interface] [node_count] [ip_addr]
set -euo pipefail

IFACE="${1:-eth1}"
NODE_CNT="${2:-8}"
IP_ADDR="${3:-192.168.1.1/24}"
TO_TIMER="${4:-50}"

echo "=== PLCA Coordinator Setup ==="
echo "Interface:  $IFACE"
echo "Node Count: $NODE_CNT"
echo "IP Address: $IP_ADDR"
echo "TO Timer:   $TO_TIMER"
echo ""

# Step 1: Verify interface exists
echo "[Step 1] Detecting interface..."
if ! ip link show "$IFACE" &>/dev/null; then
    echo "ERROR: Interface $IFACE not found."
    echo "Check EVB-LAN8670-USB connection: lsusb | grep -i microchip"
    exit 1
fi

# Verify driver
DRIVER=$(ethtool -i "$IFACE" 2>/dev/null | grep driver | awk '{print $2}' || echo "unknown")
echo "  Driver: $DRIVER"
if [ "$DRIVER" = "smsc95xx" ]; then
    echo "  Detected EVB-LAN8670-USB (LAN9500A USB bridge)"
fi

# Step 2: Configure PLCA Coordinator (Node ID 0)
echo ""
echo "[Step 2] Configuring PLCA Coordinator..."
sudo ethtool --set-plca-cfg "$IFACE" \
    enable on \
    node-id 0 \
    node-cnt "$NODE_CNT" \
    to-timer "$TO_TIMER"
echo "  PLCA configured: Coordinator (Node ID 0), $NODE_CNT nodes, TO=$TO_TIMER"

# Verify PLCA config
echo ""
echo "  PLCA Configuration:"
ethtool --get-plca-cfg "$IFACE" 2>/dev/null | sed 's/^/    /'

# Step 3: Assign IP address
echo ""
echo "[Step 3] Configuring IP address..."
sudo ip addr flush dev "$IFACE" 2>/dev/null || true
sudo ip addr add "$IP_ADDR" dev "$IFACE"
sudo ip link set "$IFACE" up
echo "  IP $IP_ADDR assigned, interface UP"

# Step 4: Verify PLCA beacon
echo ""
echo "[Step 4] Checking PLCA status..."
sleep 1
PLCA_STATUS=$(ethtool --get-plca-status "$IFACE" 2>/dev/null || echo "unavailable")
echo "$PLCA_STATUS" | sed 's/^/    /'

if echo "$PLCA_STATUS" | grep -qi "on\|yes\|active"; then
    echo ""
    echo "=== PLCA Coordinator READY ==="
else
    echo ""
    echo "WARNING: PLCA beacon may not be active yet (no followers connected)"
    echo "=== PLCA Coordinator CONFIGURED (waiting for followers) ==="
fi
