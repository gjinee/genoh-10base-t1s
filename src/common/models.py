"""Data models for the 10BASE-T1S Zenoh automotive network.

Defines dataclasses for sensor data, actuator commands, node status,
and PLCA configuration per PRD Sections 5.2 and 4.3.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


def _timestamp_ms() -> int:
    return int(time.time() * 1000)


# --- Enums ---

class SensorType(str, Enum):
    TEMPERATURE = "temperature"
    PRESSURE = "pressure"
    PROXIMITY = "proximity"
    LIGHT = "light"
    BATTERY = "battery"


class ActuatorType(str, Enum):
    LED = "led"
    MOTOR = "motor"
    RELAY = "relay"
    BUZZER = "buzzer"
    LOCK = "lock"


class ActuatorAction(str, Enum):
    SET = "set"
    GET = "get"
    RESET = "reset"


class NodeRole(str, Enum):
    SENSOR = "sensor"
    ACTUATOR = "actuator"
    MIXED = "mixed"


# --- Sensor Data (Slave → Master) ---

@dataclass
class SensorData:
    """Sensor data payload published by slave nodes.

    Payload format (PRD 5.2):
      {"value": 25.3, "unit": "celsius", "ts": 1713000000000}

    Note: node_id, zone, sensor_type are in the key expression, not payload.
    """
    value: float
    unit: str
    ts: int = field(default_factory=_timestamp_ms)

    def to_dict(self) -> dict:
        return {"value": self.value, "unit": self.unit, "ts": self.ts}

    @classmethod
    def from_dict(cls, data: dict) -> SensorData:
        return cls(value=data["value"], unit=data["unit"], ts=data.get("ts", _timestamp_ms()))


# --- Actuator Command (Master → Slave) ---

@dataclass
class ActuatorCommand:
    """Actuator command payload published by the master.

    Payload format (PRD 5.2):
      {"action": "set", "params": {"state": "on", "brightness": 80}, "ts": ...}
    """
    action: str
    params: dict = field(default_factory=dict)
    ts: int = field(default_factory=_timestamp_ms)

    def to_dict(self) -> dict:
        return {"action": self.action, "params": self.params, "ts": self.ts}

    @classmethod
    def from_dict(cls, data: dict) -> ActuatorCommand:
        return cls(
            action=data["action"],
            params=data.get("params", {}),
            ts=data.get("ts", _timestamp_ms()),
        )


# --- Node Status (Query Reply) ---

@dataclass
class NodeStatus:
    """Node status returned in response to Zenoh queries.

    Payload format (PRD 5.2):
      {"alive": true, "uptime_sec": 3600, "firmware_version": "1.0.0",
       "error_count": 0, "plca_node_id": 1, "tx_count": 15000, "rx_count": 14980}
    """
    alive: bool
    uptime_sec: int
    firmware_version: str
    error_count: int
    plca_node_id: int
    tx_count: int = 0
    rx_count: int = 0

    def to_dict(self) -> dict:
        return {
            "alive": self.alive,
            "uptime_sec": self.uptime_sec,
            "firmware_version": self.firmware_version,
            "error_count": self.error_count,
            "plca_node_id": self.plca_node_id,
            "tx_count": self.tx_count,
            "rx_count": self.rx_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> NodeStatus:
        return cls(
            alive=data["alive"],
            uptime_sec=data["uptime_sec"],
            firmware_version=data["firmware_version"],
            error_count=data["error_count"],
            plca_node_id=data["plca_node_id"],
            tx_count=data.get("tx_count", 0),
            rx_count=data.get("rx_count", 0),
        )


# --- Node Info (Internal registry) ---

@dataclass
class NodeInfo:
    """Internal representation of a registered slave node."""
    node_id: str
    zone: str
    plca_node_id: int
    role: NodeRole = NodeRole.MIXED
    alive: bool = False
    status: NodeStatus | None = None
    last_seen_ms: int = field(default_factory=_timestamp_ms)


# --- PLCA Configuration ---

@dataclass
class PLCAConfig:
    """PLCA configuration parameters for the 10BASE-T1S bus.

    See PRD Section 15 for register details.
    """
    interface: str = "eth1"
    enabled: bool = True
    node_id: int = 0          # 0 = Coordinator
    node_count: int = 8       # Max nodes on bus
    to_timer: int = 0x20      # 32 bit-times (default)
    burst_count: int = 0
    burst_timer: int = 0x80

    @property
    def is_coordinator(self) -> bool:
        return self.node_id == 0

    @property
    def worst_case_cycle_ms(self) -> float:
        """Worst-case PLCA cycle time in ms (all nodes max frame)."""
        beacon_bits = 20
        frame_bits = 1518 * 8
        total_bits = beacon_bits + (self.node_count * frame_bits)
        return round(total_bits / 10_000_000 * 1000, 2)

    @property
    def min_cycle_us(self) -> float:
        """Minimum PLCA cycle time in µs (all nodes idle)."""
        beacon_bits = 20
        total_bits = beacon_bits + (self.node_count * self.to_timer)
        return round(total_bits / 10_000_000 * 1_000_000, 1)
