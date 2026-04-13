#!/usr/bin/env bash
# Install dependencies for the Zenoh 10BASE-T1S master controller.
# Requires: Raspberry Pi OS with kernel 6.6+, ethtool 6.7+
set -euo pipefail

echo "=== Zenoh 10BASE-T1S Dependency Installer ==="

# System packages
echo "[1/5] Installing system packages..."
sudo apt-get update
sudo apt-get install -y \
    ethtool \
    python3-pip \
    python3-venv \
    cmake \
    build-essential \
    git

# Verify kernel version (need 6.6+ for LAN867x driver)
KERNEL_VER=$(uname -r | cut -d. -f1-2)
echo "[2/5] Kernel version: $KERNEL_VER (need ≥ 6.6)"
if [ "$(echo "$KERNEL_VER 6.6" | awk '{print ($1 >= $2)}')" != "1" ]; then
    echo "WARNING: Kernel $KERNEL_VER < 6.6 — LAN867x PHY driver may not be available"
fi

# Verify ethtool version (need 6.7+ for PLCA commands)
ETHTOOL_VER=$(ethtool --version 2>/dev/null | grep -oP '[\d.]+' || echo "0")
echo "[3/5] ethtool version: $ETHTOOL_VER (need ≥ 6.7)"

# Install Zenoh router (zenohd)
echo "[4/5] Installing Zenoh router..."
if ! command -v zenohd &>/dev/null; then
    if command -v cargo &>/dev/null; then
        cargo install zenoh-router
    else
        echo "Rust toolchain not found. Install via: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
        echo "Then run: cargo install zenoh-router"
    fi
else
    echo "zenohd already installed: $(which zenohd)"
fi

# Install Python dependencies
echo "[5/5] Installing Python package..."
cd "$(dirname "$0")/.."
python3 -m pip install -e ".[dev]"

echo ""
echo "=== Installation complete ==="
echo "Next steps:"
echo "  1. Connect EVB-LAN8670-USB and verify: lsusb | grep -i microchip"
echo "  2. Check interface: ip link show"
echo "  3. Run: zenoh-t1s-master start"
