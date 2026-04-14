"""Safety simulation MCP tools.

Provides E2E protection, Safety FSM, watchdog, flow monitor,
and DTC management tools for the simulation harness.
"""

from __future__ import annotations

import json
import time
from typing import Any

from claude_agent_sdk import tool

from src.common.e2e_protection import (
    E2EHeader,
    SequenceCounterState,
    e2e_decode,
    e2e_encode,
    e2e_verify,
    resolve_data_id,
)
from src.common.payloads import (
    ENCODING_JSON,
    decode,
    decode_e2e,
    encode,
    encode_e2e,
)
from src.common.safety_types import (
    E2EStatus,
    FaultType,
    SafetyState,
)
from src.master.dtc_manager import DTCManager
from src.master.e2e_supervisor import E2ESupervisor
from src.master.flow_monitor import (
    CP_ACTUATOR,
    CP_DIAG,
    CP_QUERY,
    CP_SENSOR,
    FlowMonitor,
)
from src.master.safety_log import SafetyLog
from src.master.safety_manager import SafetyManager
from src.master.watchdog import Watchdog

# Shared in-memory state for the simulation session
_safety_log: SafetyLog | None = None
_dtc_manager: DTCManager | None = None
_safety_manager: SafetyManager | None = None
_e2e_supervisor: E2ESupervisor | None = None
_flow_monitor: FlowMonitor | None = None
_watchdog: Watchdog | None = None
_counters: dict[str, SequenceCounterState] = {}


def _init_safety_stack(tmp_dir: str = "/tmp/sim_safety") -> None:
    """Initialize all safety components if not already done."""
    global _safety_log, _dtc_manager, _safety_manager
    global _e2e_supervisor, _flow_monitor, _watchdog
    import os
    os.makedirs(tmp_dir, exist_ok=True)

    if _safety_log is None:
        _safety_log = SafetyLog(path=f"{tmp_dir}/safety_log.jsonl")
    if _dtc_manager is None:
        _dtc_manager = DTCManager(path=f"{tmp_dir}/dtc_store.json")
    if _safety_manager is None:
        _safety_manager = SafetyManager(
            safety_log=_safety_log,
            dtc_manager=_dtc_manager,
            total_nodes=8,
        )
    if _e2e_supervisor is None:
        _e2e_supervisor = E2ESupervisor(
            safety_manager=_safety_manager,
            dtc_manager=_dtc_manager,
            safety_log=_safety_log,
        )
    if _flow_monitor is None:
        _flow_monitor = FlowMonitor()
    if _watchdog is None:
        _watchdog = Watchdog(timeout_sec=5.0)


def _get_counter(key_expr: str) -> SequenceCounterState:
    """Get or create a sequence counter for a key expression."""
    if key_expr not in _counters:
        _counters[key_expr] = SequenceCounterState()
    return _counters[key_expr]


def reset_safety_state() -> None:
    """Reset all safety state for a new simulation run."""
    global _safety_log, _dtc_manager, _safety_manager
    global _e2e_supervisor, _flow_monitor, _watchdog
    _safety_log = None
    _dtc_manager = None
    _safety_manager = None
    _e2e_supervisor = None
    _flow_monitor = None
    _watchdog = None
    _counters.clear()


@tool(
    "safety_e2e_encode",
    "Encode a payload with E2E protection (CRC-32 + sequence counter). "
    "Returns hex-encoded protected message for transmission.",
    {
        "key_expr": str,
        "payload_json": str,
    },
)
async def safety_e2e_encode(args: dict[str, Any]) -> dict[str, Any]:
    _init_safety_stack()
    key_expr = args["key_expr"]
    payload_json = args["payload_json"]
    data = json.loads(payload_json)
    counter = _get_counter(key_expr)

    encoded = encode_e2e(data, key_expr, counter)
    data_id = resolve_data_id(key_expr)

    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "status": "encoded",
                "key_expr": key_expr,
                "data_id": f"0x{data_id:04X}",
                "size_bytes": len(encoded),
                "hex": encoded.hex(),
                "sequence": counter.sequence - 1,
            }),
        }]
    }


@tool(
    "safety_e2e_decode",
    "Decode and verify an E2E-protected message. "
    "Checks CRC-32 integrity and returns payload with verification result.",
    {
        "hex_message": str,
    },
)
async def safety_e2e_decode(args: dict[str, Any]) -> dict[str, Any]:
    _init_safety_stack()
    raw = bytes.fromhex(args["hex_message"])
    decoded_data, header, crc_valid = decode_e2e(raw, ENCODING_JSON)

    # Feed to E2E supervisor
    raw_header, raw_payload = e2e_decode(raw)
    status = _e2e_supervisor.on_message_received(raw_header, raw_payload)

    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "crc_valid": crc_valid,
                "data_id": f"0x{header.data_id:04X}",
                "sequence": header.sequence_counter,
                "alive": header.alive_counter,
                "e2e_status": status.value,
                "payload": decoded_data,
            }),
        }]
    }


@tool(
    "safety_get_state",
    "Get current Safety FSM state and fault summary. "
    "Returns NORMAL, DEGRADED, SAFE_STATE, or FAIL_SILENT.",
    {},
)
async def safety_get_state(args: dict[str, Any]) -> dict[str, Any]:
    _init_safety_stack()
    sm = _safety_manager
    dtcs = _dtc_manager.get_all_dtcs() if _dtc_manager else []

    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "safety_state": sm.state.value,
                "output_allowed": sm.is_output_allowed,
                "offline_nodes": list(sm.offline_nodes),
                "active_dtcs": len(dtcs),
                "flow_cycles": _flow_monitor.cycle_count if _flow_monitor else 0,
                "flow_errors": _flow_monitor.error_count if _flow_monitor else 0,
            }),
        }]
    }


@tool(
    "safety_report_fault",
    "Report a fault to the Safety Manager. Triggers FSM transitions "
    "based on fault type and current state.",
    {
        "fault_type": str,
        "source": str,
    },
)
async def safety_report_fault(args: dict[str, Any]) -> dict[str, Any]:
    _init_safety_stack()
    fault_type = FaultType(args["fault_type"])
    source = args["source"]
    details = json.loads(args.get("details", "{}")) if args.get("details") else {}

    old_state = _safety_manager.state
    new_state = _safety_manager.notify_fault(fault_type, source, details)

    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "old_state": old_state.value,
                "new_state": new_state.value,
                "fault_type": fault_type.value,
                "source": source,
                "transition": old_state.value != new_state.value,
            }),
        }]
    }


@tool(
    "safety_report_recovery",
    "Report recovery of a previously faulted node. "
    "May transition FSM back toward NORMAL.",
    {
        "source": str,
    },
)
async def safety_report_recovery(args: dict[str, Any]) -> dict[str, Any]:
    _init_safety_stack()
    source = args["source"]
    old_state = _safety_manager.state
    new_state = _safety_manager.notify_recovery(source)

    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "old_state": old_state.value,
                "new_state": new_state.value,
                "source": source,
                "recovered": old_state.value != new_state.value,
            }),
        }]
    }


@tool(
    "safety_get_safe_action",
    "Get the defined safe action for an actuator type when in SAFE_STATE. "
    "Returns the fallback behavior (e.g., motor=stop, lock=lock).",
    {
        "actuator_key": str,
    },
)
async def safety_get_safe_action(args: dict[str, Any]) -> dict[str, Any]:
    _init_safety_stack()
    action = _safety_manager.get_safe_action(args["actuator_key"])
    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "actuator_key": args["actuator_key"],
                "safe_action": action,
                "current_state": _safety_manager.state.value,
            }),
        }]
    }


@tool(
    "safety_flow_checkpoint",
    "Record a flow monitor checkpoint and optionally verify the cycle. "
    "Checkpoint IDs: 1=SENSOR, 2=ACTUATOR, 3=QUERY, 4=DIAG.",
    {
        "checkpoint_id": int,
        "verify": bool,
    },
)
async def safety_flow_checkpoint(args: dict[str, Any]) -> dict[str, Any]:
    _init_safety_stack()
    cp_id = args["checkpoint_id"]
    verify = args.get("verify", False)

    _flow_monitor.checkpoint(cp_id)

    result = {
        "checkpoint_id": cp_id,
        "recorded": True,
    }

    if verify:
        ok = _flow_monitor.verify_cycle()
        result["cycle_valid"] = ok
        result["cycle_count"] = _flow_monitor.cycle_count
        result["error_count"] = _flow_monitor.error_count

    return {
        "content": [{
            "type": "text",
            "text": json.dumps(result),
        }]
    }


@tool(
    "safety_kick_watchdog",
    "Kick the software watchdog timer to prevent expiry. "
    "Must be called within the timeout period (default 5s).",
    {},
)
async def safety_kick_watchdog(args: dict[str, Any]) -> dict[str, Any]:
    _init_safety_stack()
    _watchdog.kick()
    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "status": "kicked",
                "timeout_sec": _watchdog._timeout_sec,
            }),
        }]
    }


def get_all_tools():
    """Return all safety tools for MCP server creation."""
    return [
        safety_e2e_encode,
        safety_e2e_decode,
        safety_get_state,
        safety_report_fault,
        safety_report_recovery,
        safety_get_safe_action,
        safety_flow_checkpoint,
        safety_kick_watchdog,
    ]
