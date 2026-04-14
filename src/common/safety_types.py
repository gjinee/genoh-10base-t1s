"""Safety-related types and constants for functional safety (ISO 26262).

Defines enums for safety states, fault types, E2E status, ASIL levels,
and constants for Data ID mapping, timeout configuration, sequence gap
limits, and safe actuator actions per functional_safety.md.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


def _timestamp_ms() -> int:
    return int(time.time() * 1000)


def _monotonic_ns() -> int:
    return time.monotonic_ns()


# --- Safety Enums ---

class SafetyState(str, Enum):
    """Safety state machine states (Section 3.1)."""
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    SAFE_STATE = "SAFE_STATE"
    FAIL_SILENT = "FAIL_SILENT"


class FaultType(str, Enum):
    """Fault types detected by the safety system (Section 4.1)."""
    CRC_FAILURE = "CRC_FAILURE"
    SEQ_ERROR = "SEQ_ERROR"
    TIMEOUT = "TIMEOUT"
    NODE_OFFLINE = "NODE_OFFLINE"
    PLCA_BEACON_LOST = "PLCA_BEACON_LOST"
    FLOW_ERROR = "FLOW_ERROR"
    WATCHDOG_EXPIRED = "WATCHDOG_EXPIRED"
    SENSOR_PLAUSIBILITY = "SENSOR_PLAUSIBILITY"


class E2EStatus(str, Enum):
    """E2E protection receiver state machine (Section 2.6)."""
    INIT = "INIT"
    VALID = "VALID"
    TIMEOUT = "TIMEOUT"
    INVALID = "INVALID"
    ERROR = "ERROR"


class ASILLevel(str, Enum):
    """ASIL classification levels (Section 1.3)."""
    QM = "QM"
    A = "ASIL-A"
    B = "ASIL-B"
    C = "ASIL-C"
    D = "ASIL-D"


class SafetyLogSeverity(str, Enum):
    """Safety event log severity levels (Section 6.3)."""
    SAFETY_CRITICAL = "SAFETY_CRITICAL"
    SAFETY_WARNING = "SAFETY_WARNING"
    SAFETY_INFO = "SAFETY_INFO"


class SafetyEventType(str, Enum):
    """Safety event types for the safety log (Section 6.3)."""
    E2E_CRC_FAILURE = "E2E_CRC_FAILURE"
    E2E_TIMEOUT = "E2E_TIMEOUT"
    SAFE_STATE_ENTER = "SAFE_STATE_ENTER"
    FAIL_SILENT_ENTER = "FAIL_SILENT_ENTER"
    SEQ_COUNTER_GAP = "SEQ_COUNTER_GAP"
    DEGRADED_ENTER = "DEGRADED_ENTER"
    PLCA_BEACON_LOST = "PLCA_BEACON_LOST"
    SENSOR_PLAUSIBILITY = "SENSOR_PLAUSIBILITY"
    NODE_OFFLINE = "NODE_OFFLINE"
    NODE_ONLINE = "NODE_ONLINE"
    NORMAL_RESTORED = "NORMAL_RESTORED"
    DTC_SET = "DTC_SET"
    DTC_CLEARED = "DTC_CLEARED"
    WATCHDOG_EXPIRED = "WATCHDOG_EXPIRED"
    FLOW_ERROR = "FLOW_ERROR"
    SELF_TEST_PASS = "SELF_TEST_PASS"
    SELF_TEST_FAIL = "SELF_TEST_FAIL"


# --- Data ID Mapping (Section 2.2.2) ---

DATA_ID_MAP: dict[str, int] = {
    # Sensor data (0x1xxx)
    "vehicle/*/sensor/temperature": 0x1001,
    "vehicle/*/sensor/pressure": 0x1002,
    "vehicle/*/sensor/proximity": 0x1003,
    "vehicle/*/sensor/light": 0x1004,
    "vehicle/*/sensor/battery": 0x1005,
    # Actuator commands (0x2xxx)
    "vehicle/*/actuator/led": 0x2001,
    "vehicle/*/actuator/motor": 0x2002,
    "vehicle/*/actuator/relay": 0x2003,
    "vehicle/*/actuator/buzzer": 0x2004,
    "vehicle/*/actuator/lock": 0x2005,
    # Status/control (0x3xxx)
    "vehicle/*/status": 0x3000,
    "vehicle/master/heartbeat": 0x3F01,
    "vehicle/master/diagnostics": 0x3F02,
}

# --- Timeout Configuration (Section 2.4) ---

TIMEOUT_CONFIG: dict[str, dict] = {
    "sensor/temperature": {
        "period_ms": 1000,
        "deadline_ms": 3000,
        "asil": ASILLevel.A,
        "action": "warning_log",
    },
    "sensor/proximity": {
        "period_ms": 200,
        "deadline_ms": 500,
        "asil": ASILLevel.D,
        "action": "safe_state",
    },
    "actuator_response": {
        "period_ms": 0,
        "deadline_ms": 1000,
        "asil": ASILLevel.C,
        "action": "degraded",
    },
    "master/heartbeat": {
        "period_ms": 5000,
        "deadline_ms": 15000,
        "asil": ASILLevel.B,
        "action": "slave_autonomous",
    },
    "node/liveliness": {
        "period_ms": 0,
        "deadline_ms": 30000,
        "asil": ASILLevel.A,
        "action": "node_offline",
    },
}

# --- Sequence Counter Gap Limits (Section 2.3) ---

SEQUENCE_GAP_LIMITS: dict[str, int] = {
    ASILLevel.A: 5,
    ASILLevel.B: 3,
    ASILLevel.C: 2,
    ASILLevel.D: 1,
}

# --- Safe Actuator Actions (Section 3.3) ---

SAFE_ACTIONS: dict[str, dict] = {
    "led_headlight": {"state": "on", "brightness": 50, "reason": "night visibility"},
    "led_interior": {"state": "off", "reason": "non-safety function"},
    "motor_window": {"state": "stop", "reason": "anti-pinch"},
    "motor_mirror": {"state": "stop", "reason": "hold position"},
    "relay": {"state": "off", "reason": "default safe"},
    "buzzer": {"state": "off", "reason": "non-safety function"},
    "lock_driving": {"state": "lock", "reason": "driving safety"},
    "lock_parked": {"state": "unlock", "reason": "escape possibility"},
}

# --- DTC Codes (Section 5.2) ---

DTC_CODES: dict[str, int] = {
    "bus_general_error": 0xC10000,
    "bus_no_signal": 0xC10031,
    "e2e_crc_failure": 0xC11029,
    "e2e_seq_error": 0xC11129,
    "e2e_timeout": 0xC11231,
    "master_internal_error": 0xC12049,
    "sensor_plausibility": 0xC13064,
    "node_comm_lost": 0xC14031,
    "actuator_no_response": 0xC15071,
}

# --- Sensor Plausibility Limits (Section 4.4) ---

SENSOR_RANGE_LIMITS: dict[str, dict] = {
    "temperature": {"min": -40.0, "max": 150.0, "max_rate": 10.0, "unit": "celsius/s"},
    "pressure": {"min": 0.0, "max": 1000.0, "max_rate": 500.0, "unit": "kPa/s"},
    "proximity": {"min": 0.0, "max": 500.0, "max_rate": 100.0, "unit": "cm/cycle"},
    "battery": {"min": 0.0, "max": 60.0, "max_rate": 5.0, "unit": "V/s"},
}


# --- Safety Event Dataclass (Section 6.2) ---

@dataclass
class SafetyEvent:
    """Structured safety event for the safety log."""
    seq: int
    severity: str
    event: str
    source: str
    details: dict = field(default_factory=dict)
    safety_state: str = SafetyState.NORMAL
    dtc: str = ""
    ts_ms: int = field(default_factory=_timestamp_ms)
    monotonic_ns: int = field(default_factory=_monotonic_ns)

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "ts_ms": self.ts_ms,
            "monotonic_ns": self.monotonic_ns,
            "severity": self.severity,
            "event": self.event,
            "source": self.source,
            "details": self.details,
            "safety_state": self.safety_state,
            "dtc": self.dtc,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SafetyEvent:
        return cls(
            seq=data["seq"],
            ts_ms=data.get("ts_ms", _timestamp_ms()),
            monotonic_ns=data.get("monotonic_ns", _monotonic_ns()),
            severity=data["severity"],
            event=data["event"],
            source=data["source"],
            details=data.get("details", {}),
            safety_state=data.get("safety_state", SafetyState.NORMAL),
            dtc=data.get("dtc", ""),
        )
