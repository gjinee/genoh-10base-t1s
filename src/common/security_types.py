"""Security-related types and constants for cybersecurity (ISO/SAE 21434).

Defines enums for alert severity, security event types, IDS rules,
and constants for rate limiting and freshness window.
See cybersecurity.md.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


def _timestamp_ms() -> int:
    return int(time.time() * 1000)


# --- Security Enums ---

class AlertSeverity(str, Enum):
    """IDS alert severity levels (Section 5.2)."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class SecurityEventType(str, Enum):
    """Security event types for the security log (Section 8.1)."""
    UNAUTHORIZED_PUBLISH = "UNAUTHORIZED_PUBLISH"
    MAC_FAILURE = "MAC_FAILURE"
    REPLAY_DETECTED = "REPLAY_DETECTED"
    RATE_EXCEEDED = "RATE_EXCEEDED"
    CERT_EXPIRED = "CERT_EXPIRED"
    ACL_VIOLATION = "ACL_VIOLATION"
    ANOMALY_DETECTED = "ANOMALY_DETECTED"
    AUTH_SUCCESS = "AUTH_SUCCESS"
    AUTH_FAILURE = "AUTH_FAILURE"
    KEY_ROTATED = "KEY_ROTATED"


class SecurityAction(str, Enum):
    """Actions taken in response to security events."""
    BLOCKED = "BLOCKED"
    LOGGED = "LOGGED"
    RATE_LIMITED = "RATE_LIMITED"
    ALLOWED = "ALLOWED"
    CONNECTION_REFUSED = "CONNECTION_REFUSED"


class IDSRuleID(str, Enum):
    """IDS rule identifiers (Section 5.2.2)."""
    IDS_001 = "IDS-001"  # Unauthorized key expression publish
    IDS_002 = "IDS-002"  # Message rate exceeded (flooding)
    IDS_003 = "IDS-003"  # MAC verification failure
    IDS_004 = "IDS-004"  # Replay detected (Freshness failure)
    IDS_005 = "IDS-005"  # Certificate-less connection attempt
    IDS_006 = "IDS-006"  # Abnormal payload size (> 4KB)
    IDS_007 = "IDS-007"  # Slave publishes to master key expression
    IDS_008 = "IDS-008"  # Simultaneous multiple nodes offline (≥3)
    IDS_009 = "IDS-009"  # Abnormal time communication
    IDS_010 = "IDS-010"  # CRC + MAC simultaneous failure


class NodeSecurityRole(str, Enum):
    """Role-based access control roles (Section 4.3)."""
    COORDINATOR = "COORDINATOR"
    SENSOR_NODE = "SENSOR_NODE"
    ACTUATOR_NODE = "ACTUATOR_NODE"
    MIXED_NODE = "MIXED_NODE"
    DIAGNOSTIC = "DIAGNOSTIC"


# --- Rate Limiting Configuration (Section 5.2.1) ---

RATE_LIMITS: dict[str, dict] = {
    "sensor_per_node": {
        "normal_max": 10,    # msg/s
        "warning": 50,       # msg/s
        "block": 100,        # msg/s
    },
    "actuator_command": {
        "normal_max": 5,
        "warning": 20,
        "block": 50,
    },
    "query": {
        "normal_max": 2,
        "warning": 10,
        "block": 20,
    },
    "total_bus": {
        "normal_max": 100,
        "warning": 500,
        "block": 1000,
    },
}

# Freshness value window (ms) for replay detection (Section 3.3.2)
FRESHNESS_WINDOW_MS: int = 5000

# Maximum payload size before IDS alert (Section 5.2.2 IDS-006)
MAX_PAYLOAD_SIZE: int = 4096

# Simultaneous offline nodes threshold for IDS-008
SIMULTANEOUS_OFFLINE_THRESHOLD: int = 3

# Anomaly detection baseline message count (Section 5.2.3)
ANOMALY_BASELINE_COUNT: int = 1000

# Anomaly detection sigma threshold
ANOMALY_SIGMA_THRESHOLD: float = 3.0


# --- Security Event Dataclass (Section 8.1) ---

@dataclass
class SecurityEvent:
    """Structured security event for the security log."""
    seq: int
    severity: str
    category: str
    event: str
    source_node: str = ""
    source_ip: str = ""
    target_key_expr: str = ""
    action: str = ""
    ids_rule: str = ""
    chain_hash: str = ""
    details: dict = field(default_factory=dict)
    ts_ms: int = field(default_factory=_timestamp_ms)

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "ts_ms": self.ts_ms,
            "severity": self.severity,
            "category": self.category,
            "event": self.event,
            "source": {
                "node_id": self.source_node,
                "ip": self.source_ip,
            },
            "target": {
                "key_expr": self.target_key_expr,
            },
            "action": self.action,
            "ids_rule": self.ids_rule,
            "chain_hash": self.chain_hash,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SecurityEvent:
        source = data.get("source", {})
        target = data.get("target", {})
        return cls(
            seq=data["seq"],
            ts_ms=data.get("ts_ms", _timestamp_ms()),
            severity=data["severity"],
            category=data.get("category", ""),
            event=data["event"],
            source_node=source.get("node_id", ""),
            source_ip=source.get("ip", ""),
            target_key_expr=target.get("key_expr", ""),
            action=data.get("action", ""),
            ids_rule=data.get("ids_rule", ""),
            chain_hash=data.get("chain_hash", ""),
            details=data.get("details", {}),
        )


@dataclass
class IDSAlert:
    """IDS alert structure (Section 5.3)."""
    alert_id: str
    rule_id: str
    severity: str
    source_node: str
    description: str
    evidence: dict = field(default_factory=dict)
    action_taken: str = ""
    ts_ms: int = field(default_factory=_timestamp_ms)

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "ts_ms": self.ts_ms,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "source_node": self.source_node,
            "description": self.description,
            "evidence": self.evidence,
            "action_taken": self.action_taken,
        }
