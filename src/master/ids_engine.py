"""Intrusion Detection System (IDS) Engine.

Implements rate limiting, rule-based detection, and statistical
anomaly detection per cybersecurity.md Section 5.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

from src.common.security_types import (
    ANOMALY_BASELINE_COUNT,
    ANOMALY_SIGMA_THRESHOLD,
    AlertSeverity,
    IDSAlert,
    IDSRuleID,
    MAX_PAYLOAD_SIZE,
    RATE_LIMITS,
    SIMULTANEOUS_OFFLINE_THRESHOLD,
    SecurityAction,
)

logger = logging.getLogger(__name__)


class RateLimiter:
    """Per-node sliding window rate limiter (Section 5.2.1)."""

    def __init__(self, window_sec: float = 1.0):
        self._window_sec = window_sec
        self._timestamps: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def record(self, node_id: str) -> float:
        """Record a message and return current rate (msg/s).

        Args:
            node_id: Source node identifier.

        Returns:
            Current message rate for this node.
        """
        now = time.monotonic()
        with self._lock:
            ts_list = self._timestamps[node_id]
            ts_list.append(now)
            # Prune old entries
            cutoff = now - self._window_sec
            self._timestamps[node_id] = [t for t in ts_list if t > cutoff]
            return len(self._timestamps[node_id]) / self._window_sec

    def get_rate(self, node_id: str) -> float:
        """Get current rate without recording."""
        now = time.monotonic()
        with self._lock:
            ts_list = self._timestamps.get(node_id, [])
            cutoff = now - self._window_sec
            valid = [t for t in ts_list if t > cutoff]
            return len(valid) / self._window_sec


class AnomalyDetector:
    """Statistical anomaly detection (Section 5.2.3).

    Learns baseline from first N messages, then flags 3-sigma deviations.
    """

    def __init__(
        self,
        baseline_count: int = ANOMALY_BASELINE_COUNT,
        sigma_threshold: float = ANOMALY_SIGMA_THRESHOLD,
    ):
        self._baseline_count = baseline_count
        self._sigma = sigma_threshold
        self._intervals: list[float] = []
        self._sizes: list[int] = []
        self._last_time: float = 0.0
        self._baseline_ready = False
        self._interval_mean: float = 0.0
        self._interval_std: float = 0.0
        self._size_mean: float = 0.0
        self._size_std: float = 0.0

    @property
    def baseline_ready(self) -> bool:
        return self._baseline_ready

    def record(self, payload_size: int) -> list[str]:
        """Record a message and check for anomalies.

        Args:
            payload_size: Size of the message payload.

        Returns:
            List of anomaly descriptions (empty if normal).
        """
        now = time.monotonic()
        anomalies = []

        if self._last_time > 0:
            interval = now - self._last_time
            self._intervals.append(interval)
        self._last_time = now
        self._sizes.append(payload_size)

        if not self._baseline_ready:
            if len(self._sizes) >= self._baseline_count:
                self._compute_baseline()
            return anomalies

        # Check interval anomaly
        if len(self._intervals) > 1:
            interval = self._intervals[-1]
            if self._interval_std > 0:
                z = abs(interval - self._interval_mean) / self._interval_std
                if z > self._sigma:
                    anomalies.append(
                        f"Interval anomaly: {interval:.3f}s (mean={self._interval_mean:.3f}, z={z:.1f})"
                    )

        # Check size anomaly
        if self._size_std > 0:
            z = abs(payload_size - self._size_mean) / self._size_std
            if z > self._sigma:
                anomalies.append(
                    f"Size anomaly: {payload_size}B (mean={self._size_mean:.0f}, z={z:.1f})"
                )

        return anomalies

    def _compute_baseline(self) -> None:
        if self._intervals:
            self._interval_mean = sum(self._intervals) / len(self._intervals)
            variance = sum((x - self._interval_mean) ** 2 for x in self._intervals) / len(self._intervals)
            self._interval_std = math.sqrt(variance) if variance > 0 else 0
        if self._sizes:
            self._size_mean = sum(self._sizes) / len(self._sizes)
            variance = sum((x - self._size_mean) ** 2 for x in self._sizes) / len(self._sizes)
            self._size_std = math.sqrt(variance) if variance > 0 else 0
        self._baseline_ready = True


class IDSEngine:
    """Intrusion Detection System engine combining multiple detectors.

    Integrates:
    - Rate limiting per node
    - 10 rule-based detection rules
    - Statistical anomaly detection
    """

    def __init__(self, security_log=None):
        self._rate_limiter = RateLimiter()
        self._anomaly_detector = AnomalyDetector()
        self._security_log = security_log
        self._alert_counter = 0
        self._lock = threading.Lock()
        self._offline_nodes: set[str] = set()

    def check_message(
        self,
        source_node: str,
        key_expr: str,
        payload_size: int,
        mac_valid: bool = True,
        freshness_valid: bool = True,
        crc_valid: bool = True,
    ) -> list[IDSAlert]:
        """Check an incoming message against all IDS rules.

        Args:
            source_node: Source node identifier.
            key_expr: Zenoh key expression.
            payload_size: Size of the payload in bytes.
            mac_valid: Whether MAC verification passed.
            freshness_valid: Whether freshness check passed.
            crc_valid: Whether CRC check passed.

        Returns:
            List of triggered IDS alerts (empty if clean).
        """
        alerts: list[IDSAlert] = []

        # IDS-003: MAC verification failure
        if not mac_valid:
            alerts.append(self._create_alert(
                IDSRuleID.IDS_003, AlertSeverity.CRITICAL, source_node,
                "MAC verification failure",
                {"key_expr": key_expr},
                SecurityAction.BLOCKED,
            ))

        # IDS-004: Replay detected
        if not freshness_valid and mac_valid:
            alerts.append(self._create_alert(
                IDSRuleID.IDS_004, AlertSeverity.HIGH, source_node,
                "Replay detected (freshness check failed)",
                {"key_expr": key_expr},
                SecurityAction.BLOCKED,
            ))

        # IDS-002: Rate limit check
        rate = self._rate_limiter.record(source_node)
        limits = RATE_LIMITS.get("sensor_per_node", {})
        if rate > limits.get("block", 100):
            alerts.append(self._create_alert(
                IDSRuleID.IDS_002, AlertSeverity.HIGH, source_node,
                f"Message rate exceeded block threshold: {rate:.0f} msg/s",
                {"rate": rate, "threshold": limits["block"]},
                SecurityAction.BLOCKED,
            ))
        elif rate > limits.get("warning", 50):
            alerts.append(self._create_alert(
                IDSRuleID.IDS_002, AlertSeverity.MEDIUM, source_node,
                f"Message rate exceeded warning threshold: {rate:.0f} msg/s",
                {"rate": rate, "threshold": limits["warning"]},
                SecurityAction.RATE_LIMITED,
            ))

        # IDS-006: Abnormal payload size
        if payload_size > MAX_PAYLOAD_SIZE:
            alerts.append(self._create_alert(
                IDSRuleID.IDS_006, AlertSeverity.MEDIUM, source_node,
                f"Abnormal payload size: {payload_size}B > {MAX_PAYLOAD_SIZE}B",
                {"payload_size": payload_size},
                SecurityAction.BLOCKED,
            ))

        # IDS-007: Slave publishes to master key expression
        if "master/" in key_expr and not source_node.startswith("master"):
            alerts.append(self._create_alert(
                IDSRuleID.IDS_007, AlertSeverity.CRITICAL, source_node,
                f"Slave publishing to master key expression: {key_expr}",
                {"key_expr": key_expr},
                SecurityAction.BLOCKED,
            ))

        # IDS-010: CRC + MAC simultaneous failure
        if not crc_valid and not mac_valid:
            alerts.append(self._create_alert(
                IDSRuleID.IDS_010, AlertSeverity.CRITICAL, source_node,
                "CRC and MAC simultaneous failure",
                {"key_expr": key_expr},
                SecurityAction.BLOCKED,
            ))

        # Anomaly detection
        anomalies = self._anomaly_detector.record(payload_size)
        for anomaly in anomalies:
            alerts.append(self._create_alert(
                IDSRuleID.IDS_009, AlertSeverity.LOW, source_node,
                anomaly, {}, SecurityAction.LOGGED,
            ))

        # Log all alerts
        for alert in alerts:
            self._log_alert(alert)

        return alerts

    def report_node_offline(self, node_id: str) -> list[IDSAlert]:
        """Report a node going offline. Checks IDS-008."""
        alerts = []
        should_alert = False
        offline_count = 0
        offline_list = []
        with self._lock:
            self._offline_nodes.add(node_id)
            offline_count = len(self._offline_nodes)
            offline_list = list(self._offline_nodes)
            should_alert = offline_count >= SIMULTANEOUS_OFFLINE_THRESHOLD
        if should_alert:
            alerts.append(self._create_alert(
                IDSRuleID.IDS_008, AlertSeverity.HIGH, node_id,
                f"Simultaneous nodes offline: {offline_count}",
                {"offline_nodes": offline_list},
                SecurityAction.LOGGED,
            ))
        for alert in alerts:
            self._log_alert(alert)
        return alerts

    def report_node_online(self, node_id: str) -> None:
        with self._lock:
            self._offline_nodes.discard(node_id)

    def check_acl(
        self,
        source_node: str,
        key_expr: str,
        allowed_key_exprs: list[str],
    ) -> list[IDSAlert]:
        """Check if source_node is authorized for key_expr. IDS-001."""
        alerts = []
        authorized = any(
            self._key_expr_matches(key_expr, pattern)
            for pattern in allowed_key_exprs
        )
        if not authorized:
            alerts.append(self._create_alert(
                IDSRuleID.IDS_001, AlertSeverity.CRITICAL, source_node,
                f"Unauthorized publish to {key_expr}",
                {"key_expr": key_expr, "allowed": allowed_key_exprs},
                SecurityAction.BLOCKED,
            ))
            for alert in alerts:
                self._log_alert(alert)
        return alerts

    def _create_alert(
        self,
        rule_id: IDSRuleID,
        severity: AlertSeverity,
        source_node: str,
        description: str,
        evidence: dict,
        action: SecurityAction,
    ) -> IDSAlert:
        with self._lock:
            self._alert_counter += 1
            alert_id = f"IDS-{int(time.time())}-{self._alert_counter:05d}"
        return IDSAlert(
            alert_id=alert_id,
            rule_id=rule_id.value,
            severity=severity.value,
            source_node=source_node,
            description=description,
            evidence=evidence,
            action_taken=action.value,
        )

    def _log_alert(self, alert: IDSAlert) -> None:
        logger.warning("IDS Alert [%s] %s: %s", alert.rule_id, alert.severity, alert.description)
        if self._security_log:
            self._security_log.log_event(
                severity=alert.severity,
                event=alert.description,
                category="INTRUSION_DETECTION",
                source_node=alert.source_node,
                ids_rule=alert.rule_id,
                action=alert.action_taken,
                details=alert.evidence,
            )

    @staticmethod
    def _key_expr_matches(key_expr: str, pattern: str) -> bool:
        """Simple wildcard matching for Zenoh key expressions."""
        if pattern == key_expr:
            return True
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            return key_expr.startswith(prefix)
        if pattern.endswith("/*"):
            prefix = pattern[:-2]
            parts = key_expr.split("/")
            pattern_parts = prefix.split("/")
            if len(parts) == len(pattern_parts) + 1:
                return key_expr.startswith(prefix + "/")
        return False
