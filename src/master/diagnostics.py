"""Diagnostics and monitoring module.

Implements PRD FR-007: Diagnostics and monitoring.
- Real-time network traffic statistics
- PLCA status monitoring (beacon, collisions)
- Per-node communication quality metrics
- Structured log output for CLI/dashboard

Collects data from:
- NetworkSetup (PLCA status via ethtool)
- ZenohMaster (message counts, latency)
- NodeManager (node health, online/offline)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from src.common.models import PLCAConfig
from src.master.network_setup import NetworkSetup
from src.master.node_manager import NodeManager

logger = logging.getLogger(__name__)


@dataclass
class TrafficStats:
    """Per-key-expression traffic counters."""
    messages_received: int = 0
    messages_sent: int = 0
    bytes_received: int = 0
    bytes_sent: int = 0
    last_message_ms: int = 0


@dataclass
class DiagnosticReport:
    """Structured diagnostic report."""
    timestamp_ms: int = 0
    uptime_sec: int = 0

    # PLCA status
    plca_beacon_active: bool = False
    plca_collision_count: int = 0
    plca_cycle_count: int = 0

    # Node health
    total_nodes: int = 0
    online_nodes: int = 0
    offline_nodes: list[str] = field(default_factory=list)

    # Traffic
    total_messages_rx: int = 0
    total_messages_tx: int = 0
    messages_per_sec: float = 0.0

    # Alerts
    alerts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp_ms": self.timestamp_ms,
            "uptime_sec": self.uptime_sec,
            "plca": {
                "beacon_active": self.plca_beacon_active,
                "collision_count": self.plca_collision_count,
                "cycle_count": self.plca_cycle_count,
            },
            "nodes": {
                "total": self.total_nodes,
                "online": self.online_nodes,
                "offline": self.offline_nodes,
            },
            "traffic": {
                "rx": self.total_messages_rx,
                "tx": self.total_messages_tx,
                "msg_per_sec": self.messages_per_sec,
            },
            "alerts": self.alerts,
        }

    def format_text(self) -> str:
        """Human-readable diagnostic report."""
        lines = [
            "=== Network Diagnostic Report ===",
            f"Timestamp: {self.timestamp_ms}",
            f"Uptime: {self.uptime_sec}s",
            "",
            "PLCA Status:",
            f"  Beacon: {'ACTIVE' if self.plca_beacon_active else 'INACTIVE'}",
            f"  Collisions: {self.plca_collision_count}",
            f"  Cycles: {self.plca_cycle_count}",
            "",
            "Node Health:",
            f"  Online: {self.online_nodes}/{self.total_nodes}",
        ]
        if self.offline_nodes:
            lines.append(f"  Offline: {', '.join(self.offline_nodes)}")

        lines.extend([
            "",
            "Traffic:",
            f"  RX: {self.total_messages_rx} msgs",
            f"  TX: {self.total_messages_tx} msgs",
            f"  Rate: {self.messages_per_sec:.1f} msg/s",
        ])

        if self.alerts:
            lines.append("")
            lines.append("ALERTS:")
            for alert in self.alerts:
                lines.append(f"  ! {alert}")

        lines.append("=================================")
        return "\n".join(lines)


class DiagnosticsCollector:
    """Collects and reports network diagnostics.

    Periodically polls PLCA status and aggregates traffic/node metrics.
    """

    def __init__(
        self,
        network: NetworkSetup,
        node_manager: NodeManager,
    ) -> None:
        self._network = network
        self._node_manager = node_manager
        self._start_time = time.time()
        self._traffic: dict[str, TrafficStats] = {}
        self._total_rx = 0
        self._total_tx = 0
        self._last_report_time = time.time()
        self._last_report_rx = 0
        self._running = False

    def record_rx(self, key_expr: str, byte_count: int = 0) -> None:
        """Record a received message."""
        self._total_rx += 1
        if key_expr not in self._traffic:
            self._traffic[key_expr] = TrafficStats()
        stats = self._traffic[key_expr]
        stats.messages_received += 1
        stats.bytes_received += byte_count
        stats.last_message_ms = int(time.time() * 1000)

    def record_tx(self, key_expr: str, byte_count: int = 0) -> None:
        """Record a sent message."""
        self._total_tx += 1
        if key_expr not in self._traffic:
            self._traffic[key_expr] = TrafficStats()
        stats = self._traffic[key_expr]
        stats.messages_sent += 1
        stats.bytes_sent += byte_count
        stats.last_message_ms = int(time.time() * 1000)

    async def collect_report(self) -> DiagnosticReport:
        """Collect a full diagnostic report."""
        now = time.time()
        elapsed = now - self._last_report_time
        msg_rate = (self._total_rx - self._last_report_rx) / elapsed if elapsed > 0 else 0.0

        report = DiagnosticReport(
            timestamp_ms=int(now * 1000),
            uptime_sec=int(now - self._start_time),
            total_nodes=self._node_manager.node_count,
            online_nodes=self._node_manager.online_count,
            total_messages_rx=self._total_rx,
            total_messages_tx=self._total_tx,
            messages_per_sec=round(msg_rate, 1),
        )

        # Offline nodes
        for node_id, info in self._node_manager.nodes.items():
            if not info.alive:
                report.offline_nodes.append(node_id)

        # PLCA status
        try:
            plca_status = await self._network.get_plca_status()
            report.plca_beacon_active = plca_status.beacon_active
        except Exception as e:
            report.alerts.append(f"PLCA status check failed: {e}")

        # Generate alerts
        if not report.plca_beacon_active:
            report.alerts.append("PLCA beacon INACTIVE — bus communication may be impaired")
        if report.offline_nodes:
            report.alerts.append(
                f"Nodes offline: {', '.join(report.offline_nodes)}"
            )
        if report.online_nodes == 0 and report.total_nodes > 0:
            report.alerts.append("ALL nodes offline — check network connectivity")

        self._last_report_time = now
        self._last_report_rx = self._total_rx
        return report

    async def monitor_loop(self, interval_sec: float = 10.0) -> None:
        """Run periodic diagnostics collection.

        Args:
            interval_sec: Seconds between diagnostic reports.
        """
        self._running = True
        logger.info("Diagnostics monitor started (interval: %.1fs)", interval_sec)

        while self._running:
            report = await self.collect_report()
            logger.info("\n%s", report.format_text())
            await asyncio.sleep(interval_sec)

    def stop(self) -> None:
        """Stop the monitoring loop."""
        self._running = False
