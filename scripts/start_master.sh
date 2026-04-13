#!/usr/bin/env bash
# Start the complete Zenoh 10BASE-T1S master system.
# PRD Section 6: Startup Sequence (Steps 1-8)
#
# Usage: ./start_master.sh [--scenario door_zone]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
IFACE="${T1S_IFACE:-eth1}"
IP_ADDR="${T1S_IP:-192.168.1.1/24}"
SCENARIO="${1:---scenario}"
SCENARIO_ARG="${2:-}"

echo "=== Zenoh 10BASE-T1S Master Startup ==="
echo "Project: $PROJECT_DIR"
echo "Interface: $IFACE"
echo ""

# Step 1-4: PLCA setup
echo "[1/3] Setting up PLCA..."
sudo "$SCRIPT_DIR/setup_plca.sh" "$IFACE" 8 "$IP_ADDR"
echo ""

# Step 5: Start zenohd router (if not already running)
echo "[2/3] Starting Zenoh router..."
if pgrep -x zenohd >/dev/null; then
    echo "  zenohd already running (PID: $(pgrep -x zenohd))"
else
    ZENOH_CONFIG="$PROJECT_DIR/config/master_config.json5"
    if [ -f "$ZENOH_CONFIG" ]; then
        zenohd --config "$ZENOH_CONFIG" &
    else
        zenohd --listen "tcp/0.0.0.0:7447" &
    fi
    ZENOHD_PID=$!
    echo "  zenohd started (PID: $ZENOHD_PID)"
    sleep 2  # Wait for router to initialize
fi
echo ""

# Step 6-8: Start master application
echo "[3/3] Starting master application..."
cd "$PROJECT_DIR"

if [ -n "$SCENARIO_ARG" ]; then
    exec python3 -m src.master.main start --interface "$IFACE" --scenario "$SCENARIO_ARG"
else
    exec python3 -m src.master.main start --interface "$IFACE"
fi
