"""WebSocket message protocol for Master ↔ Slave GUI communication."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum


class MsgType(str, Enum):
    # Sensor / Actuator
    SENSOR_DATA = "sensor_data"
    ACTUATOR_CMD = "actuator_cmd"
    # Safety
    SAFETY_STATE = "safety_state"
    E2E_STATUS = "e2e_status"
    WATCHDOG = "watchdog"
    FLOW_CHECKPOINT = "flow_checkpoint"
    DTC_UPDATE = "dtc_update"
    # Security
    IDS_ALERT = "ids_alert"
    SECOC_STATUS = "secoc_status"
    ACL_EVENT = "acl_event"
    # Node / Bus
    NODE_STATUS = "node_status"
    NODE_REGISTER = "node_register"
    NODE_OFFLINE = "node_offline"
    PLCA_STATUS = "plca_status"
    BUS_MESSAGE = "bus_message"
    # Scenario / Agent
    SCENARIO_LOAD = "scenario_load"
    SCENARIO_STEP = "scenario_step"
    SCENARIO_COMPLETE = "scenario_complete"
    AGENT_LOG = "agent_log"
    # Control
    CMD_START = "cmd_start"
    CMD_STOP = "cmd_stop"
    CMD_MANUAL_ACTUATOR = "cmd_manual_actuator"
    CMD_INJECT_FAULT = "cmd_inject_fault"
    CMD_ATTACK = "cmd_attack"
    CMD_RESET_SAFETY = "cmd_reset_safety"
    CMD_KICK_WATCHDOG = "cmd_kick_watchdog"
    # System
    PING = "ping"
    PONG = "pong"
    ERROR = "error"
    INIT_STATE = "init_state"


@dataclass
class WSMessage:
    type: str
    source: str  # "master" | "slave" | "engine" | "agent"
    payload: dict = field(default_factory=dict)
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> WSMessage:
        data = json.loads(raw)
        return cls(
            type=data["type"],
            source=data.get("source", "unknown"),
            payload=data.get("payload", {}),
            timestamp=data.get("timestamp", int(time.time() * 1000)),
        )
