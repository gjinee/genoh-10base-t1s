"""10BASE-T1S network interface and PLCA configuration.

Manages the EVB-LAN8670-USB hardware interface via Linux ethtool and ip commands.
Implements PRD FR-001: PLCA Coordinator setup.

Physical layer:
  USB → LAN9500A (USB-CDC-ECM, smsc95xx driver) → LAN8670 (10BASE-T1S MAC-PHY)
  Linux sees this as a standard Ethernet interface (typically eth1).

PLCA is configured via ethtool's PLCA subcommands (requires ethtool ≥ 6.7):
  ethtool --set-plca-cfg <iface> enable on node-id 0 node-cnt 8 to-timer 0x20
  ethtool --get-plca-cfg <iface>
  ethtool --get-plca-status <iface>
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass

from src.common.models import PLCAConfig

logger = logging.getLogger(__name__)


@dataclass
class PLCAStatus:
    """Parsed output of `ethtool --get-plca-status`."""
    supported: bool = False
    enabled: bool = False
    node_id: int = -1
    node_count: int = 0
    to_timer: int = 0
    beacon_active: bool = False


class NetworkSetup:
    """Manages 10BASE-T1S network interface and PLCA configuration.

    This class wraps Linux ethtool and ip commands to configure the
    EVB-LAN8670-USB as a PLCA Coordinator on the 10BASE-T1S bus.
    """

    def __init__(self, config: PLCAConfig) -> None:
        self.config = config
        self._iface = config.interface
        self._ethtool = shutil.which("ethtool")
        if not self._ethtool:
            logger.warning("ethtool not found in PATH — PLCA commands will fail")

    # --- Interface detection ---

    async def detect_interface(self) -> bool:
        """Check if the 10BASE-T1S interface exists and is a USB-CDC-ECM device.

        The EVB-LAN8670-USB appears as a USB-CDC-ECM interface via the smsc95xx driver.
        """
        try:
            result = await self._run(["ip", "link", "show", self._iface])
            if result.returncode != 0:
                logger.error("Interface %s not found", self._iface)
                return False

            # Verify it's using the smsc95xx driver (LAN9500A USB bridge)
            driver_result = await self._run(
                ["ethtool", "-i", self._iface]
            )
            if driver_result.returncode == 0:
                output = driver_result.stdout
                if "smsc95xx" in output:
                    logger.info("Detected EVB-LAN8670-USB on %s (smsc95xx)", self._iface)
                    return True
                logger.warning(
                    "Interface %s exists but driver is not smsc95xx: %s",
                    self._iface, output,
                )
            return True  # Interface exists even if driver check fails
        except FileNotFoundError:
            logger.error("Required tools (ip, ethtool) not found")
            return False

    async def get_link_status(self) -> bool:
        """Check if the interface link is up."""
        result = await self._run(
            ["ip", "-o", "link", "show", self._iface]
        )
        if result.returncode != 0:
            return False
        return "state UP" in result.stdout or "LOWER_UP" in result.stdout

    # --- IP configuration ---

    async def configure_ip(self, ip_addr: str = "192.168.1.1/24") -> bool:
        """Assign IP address and bring up the interface.

        PRD Section 6, Step [3]:
          ip addr add 192.168.1.1/24 dev eth1
          ip link set eth1 up
        """
        # Flush existing addresses
        await self._run(["sudo", "ip", "addr", "flush", "dev", self._iface])

        # Assign new address
        result = await self._run(
            ["sudo", "ip", "addr", "add", ip_addr, "dev", self._iface]
        )
        if result.returncode != 0:
            logger.error("Failed to assign IP %s to %s: %s", ip_addr, self._iface, result.stderr)
            return False

        # Bring interface up
        result = await self._run(
            ["sudo", "ip", "link", "set", self._iface, "up"]
        )
        if result.returncode != 0:
            logger.error("Failed to bring up %s: %s", self._iface, result.stderr)
            return False

        logger.info("Configured %s with IP %s", self._iface, ip_addr)
        return True

    # --- PLCA configuration ---

    async def configure_plca(self) -> bool:
        """Configure PLCA Coordinator on the 10BASE-T1S interface.

        PRD Section 6, Step [2]:
          ethtool --set-plca-cfg eth1 enable on node-id 0 node-cnt 8 to-timer 50

        PLCA registers (MMD 31):
          PLCA_CTRL0 (0xCA01): EN bit 15 — enable PLCA
          PLCA_CTRL1 (0xCA02): NCNT[15:8] node count, ID[7:0] node ID
          PLCA_TOTMR (0xCA04): TO timer[7:0]
        """
        cmd = [
            "sudo", "ethtool", "--set-plca-cfg", self._iface,
            "enable", "on" if self.config.enabled else "off",
            "node-id", str(self.config.node_id),
            "node-cnt", str(self.config.node_count),
            "to-timer", str(self.config.to_timer),
        ]

        result = await self._run(cmd)
        if result.returncode != 0:
            logger.error("PLCA configuration failed: %s", result.stderr)
            return False

        logger.info(
            "PLCA configured: coordinator=%s, node_id=%d, node_cnt=%d, to_timer=%d",
            self.config.is_coordinator, self.config.node_id,
            self.config.node_count, self.config.to_timer,
        )
        return True

    async def get_plca_config(self) -> PLCAStatus:
        """Read current PLCA configuration via ethtool.

        Parses output of: ethtool --get-plca-cfg <iface>
        """
        status = PLCAStatus()
        result = await self._run(
            ["ethtool", "--get-plca-cfg", self._iface]
        )
        if result.returncode != 0:
            logger.error("Failed to read PLCA config: %s", result.stderr)
            return status

        output = result.stdout
        status.supported = "supported" in output.lower()
        status.enabled = self._parse_bool(output, r"PLCA status:\s*(enabled|on)")
        status.node_id = self._parse_int(output, r"PLCA node id:\s*(\d+)")
        status.node_count = self._parse_int(output, r"PLCA node count:\s*(\d+)")
        status.to_timer = self._parse_int(output, r"PLCA TO timer:\s*(\d+)")
        return status

    async def get_plca_status(self) -> PLCAStatus:
        """Read PLCA runtime status (beacon detection).

        Parses output of: ethtool --get-plca-status <iface>
        PLCA_STS register (0xCA03): PST bit 15 indicates beacon detected.
        """
        status = await self.get_plca_config()
        result = await self._run(
            ["ethtool", "--get-plca-status", self._iface]
        )
        if result.returncode == 0:
            status.beacon_active = self._parse_bool(
                result.stdout, r"(?:plca-status|PLCA status)\s+(?:on|yes)"
            )
        return status

    async def verify_plca_beacon(self) -> bool:
        """Verify that the PLCA beacon is active (coordinator is generating beacons).

        PRD Section 6, Step [4].
        """
        status = await self.get_plca_status()
        if status.beacon_active:
            logger.info("PLCA beacon active on %s", self._iface)
            return True
        logger.warning("PLCA beacon NOT active on %s", self._iface)
        return False

    # --- Full initialization sequence ---

    async def initialize(self, ip_addr: str = "192.168.1.1/24") -> bool:
        """Run the complete network initialization sequence (PRD Section 6, Steps 1-4).

        1. Detect interface
        2. Configure PLCA Coordinator
        3. Assign IP address
        4. Verify PLCA beacon
        """
        logger.info("=== Network initialization: %s ===", self._iface)

        # Step 1: Detect interface
        if not await self.detect_interface():
            logger.error("Step 1 FAILED: Interface %s not detected", self._iface)
            return False
        logger.info("Step 1 OK: Interface %s detected", self._iface)

        # Step 2: Configure PLCA
        if not await self.configure_plca():
            logger.error("Step 2 FAILED: PLCA configuration failed")
            return False
        logger.info("Step 2 OK: PLCA configured as Coordinator (Node ID 0)")

        # Step 3: Configure IP
        if not await self.configure_ip(ip_addr):
            logger.error("Step 3 FAILED: IP configuration failed")
            return False
        logger.info("Step 3 OK: IP %s assigned", ip_addr)

        # Step 4: Verify beacon
        if not await self.verify_plca_beacon():
            logger.warning("Step 4 WARNING: Beacon not yet active (may need slaves)")
        else:
            logger.info("Step 4 OK: PLCA beacon active")

        logger.info("=== Network initialization complete ===")
        return True

    # --- Error recovery (PRD Section 4.4) ---

    async def recover_link(self, max_retries: int = 10, interval_sec: float = 30.0) -> bool:
        """Attempt to recover a down link with retries.

        PRD error handling: "30초 간격 재연결 시도 (최대 10회)"
        """
        for attempt in range(1, max_retries + 1):
            logger.info("Link recovery attempt %d/%d on %s", attempt, max_retries, self._iface)
            if await self.get_link_status():
                logger.info("Link recovered on %s", self._iface)
                return True
            # Try to re-initialize
            await self._run(["sudo", "ip", "link", "set", self._iface, "down"])
            await asyncio.sleep(1)
            await self._run(["sudo", "ip", "link", "set", self._iface, "up"])
            await asyncio.sleep(interval_sec)

        logger.error("Link recovery failed after %d attempts", max_retries)
        return False

    async def recover_plca(self) -> bool:
        """Re-initialize PLCA after beacon loss.

        PRD error handling: "PLCA 재설정 시도 → 실패 시 인터페이스 재초기화"
        """
        logger.info("Attempting PLCA recovery on %s", self._iface)
        if await self.configure_plca():
            await asyncio.sleep(2)
            if await self.verify_plca_beacon():
                return True

        # Full interface re-initialization
        logger.warning("PLCA re-config failed, re-initializing interface")
        await self._run(["sudo", "ip", "link", "set", self._iface, "down"])
        await asyncio.sleep(2)
        await self._run(["sudo", "ip", "link", "set", self._iface, "up"])
        await asyncio.sleep(2)
        return await self.configure_plca()

    # --- Helpers ---

    @staticmethod
    async def _run(cmd: list[str]) -> subprocess.CompletedProcess:
        """Run a shell command asynchronously."""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        return subprocess.CompletedProcess(
            cmd, proc.returncode,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
        )

    @staticmethod
    def _parse_int(text: str, pattern: str, default: int = 0) -> int:
        match = re.search(pattern, text, re.IGNORECASE)
        return int(match.group(1)) if match else default

    @staticmethod
    def _parse_bool(text: str, pattern: str) -> bool:
        return bool(re.search(pattern, text, re.IGNORECASE))
