"""Security simulation MCP tools.

Provides SecOC encode/decode, IDS checking, ACL verification,
and key management tools for the simulation harness.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from claude_agent_sdk import tool

from src.common.e2e_protection import SequenceCounterState
from src.common.payloads import (
    ENCODING_JSON,
    decode_secoc,
    encode_secoc,
)
from src.common.security_types import (
    AlertSeverity,
    IDSRuleID,
    NodeSecurityRole,
)
from src.master.acl_manager import ACLManager
from src.master.ids_engine import IDSEngine
from src.master.key_manager import KeyManager
from src.master.secoc import FreshnessCounter
from src.master.security_log import SecurityLog

# Shared in-memory state for the simulation session
_security_log: SecurityLog | None = None
_ids_engine: IDSEngine | None = None
_acl_manager: ACLManager | None = None
_key_manager: KeyManager | None = None
_node_keys: dict[str, bytes] = {}
_counters: dict[str, SequenceCounterState] = {}
_alerts_history: list[dict] = []


def _init_security_stack(tmp_dir: str = "/tmp/sim_security") -> None:
    """Initialize all security components if not already done."""
    global _security_log, _ids_engine, _acl_manager, _key_manager
    os.makedirs(tmp_dir, exist_ok=True)

    if _security_log is None:
        _security_log = SecurityLog(path=f"{tmp_dir}/security_log.jsonl")
    if _ids_engine is None:
        _ids_engine = IDSEngine(security_log=_security_log)
    if _acl_manager is None:
        _acl_manager = ACLManager()
    if _key_manager is None:
        _key_manager = KeyManager(key_dir=tmp_dir)
        _key_manager.load_master_key()


def _get_counter(key_expr: str) -> SequenceCounterState:
    if key_expr not in _counters:
        _counters[key_expr] = SequenceCounterState()
    return _counters[key_expr]


def _get_node_key(node_id: str) -> bytes:
    if node_id not in _node_keys:
        _node_keys[node_id] = _key_manager.derive_node_key(node_id)
    return _node_keys[node_id]


def reset_security_state() -> None:
    """Reset all security state for a new simulation run."""
    global _security_log, _ids_engine, _acl_manager, _key_manager
    _security_log = None
    _ids_engine = None
    _acl_manager = None
    _key_manager = None
    _node_keys.clear()
    _counters.clear()
    _alerts_history.clear()


@tool(
    "security_secoc_encode",
    "Encode a payload with full E2E + SecOC protection (CRC + HMAC-SHA256). "
    "Uses per-node derived HMAC key.",
    {
        "node_id": str,
        "key_expr": str,
        "payload_json": str,
    },
)
async def security_secoc_encode(args: dict[str, Any]) -> dict[str, Any]:
    _init_security_stack()
    node_id = args["node_id"]
    key_expr = args["key_expr"]
    data = json.loads(args["payload_json"])
    counter = _get_counter(f"{node_id}:{key_expr}")
    node_key = _get_node_key(node_id)

    encoded = encode_secoc(data, key_expr, counter, node_key, ENCODING_JSON)

    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "status": "encoded",
                "node_id": node_id,
                "key_expr": key_expr,
                "size_bytes": len(encoded),
                "hex": encoded.hex(),
                "protection": "E2E+SecOC",
            }),
        }]
    }


@tool(
    "security_secoc_decode",
    "Decode and verify a SecOC + E2E protected message. "
    "Checks MAC (HMAC-SHA256) and CRC-32 integrity.",
    {
        "node_id": str,
        "hex_message": str,
    },
)
async def security_secoc_decode(args: dict[str, Any]) -> dict[str, Any]:
    _init_security_stack()
    node_id = args["node_id"]
    raw = bytes.fromhex(args["hex_message"])
    node_key = _get_node_key(node_id)

    decoded, header, crc_valid, mac_valid = decode_secoc(raw, node_key)

    result = {
        "mac_valid": mac_valid,
        "crc_valid": crc_valid,
    }
    if decoded is not None:
        result["payload"] = decoded
        result["data_id"] = f"0x{header.data_id:04X}"
        result["sequence"] = header.sequence_counter
    else:
        result["payload"] = None
        result["error"] = "MAC or CRC verification failed"

    return {
        "content": [{
            "type": "text",
            "text": json.dumps(result),
        }]
    }


@tool(
    "security_ids_check",
    "Check a message against IDS rules. Returns any triggered alerts "
    "(rate limit, MAC failure, replay, oversized payload, etc.).",
    {
        "source_node": str,
        "key_expr": str,
        "payload_size": int,
        "mac_valid": bool,
        "freshness_valid": bool,
        "crc_valid": bool,
    },
)
async def security_ids_check(args: dict[str, Any]) -> dict[str, Any]:
    _init_security_stack()
    alerts = _ids_engine.check_message(
        source_node=args["source_node"],
        key_expr=args["key_expr"],
        payload_size=args.get("payload_size", 50),
        mac_valid=args.get("mac_valid", True),
        freshness_valid=args.get("freshness_valid", True),
        crc_valid=args.get("crc_valid", True),
    )

    alert_dicts = []
    for a in alerts:
        d = {
            "alert_id": a.alert_id,
            "rule_id": a.rule_id,
            "severity": a.severity,
            "source_node": a.source_node,
            "description": a.description,
            "action_taken": a.action_taken,
        }
        alert_dicts.append(d)
        _alerts_history.append(d)

    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "alert_count": len(alerts),
                "alerts": alert_dicts,
                "total_alerts_session": len(_alerts_history),
            }),
        }]
    }


@tool(
    "security_acl_check",
    "Check if a node is authorized to access a key expression. "
    "Uses role-based ACL policy.",
    {
        "source_node": str,
        "key_expr": str,
    },
)
async def security_acl_check(args: dict[str, Any]) -> dict[str, Any]:
    _init_security_stack()
    source_node = args["source_node"]
    key_expr = args["key_expr"]

    authorized = _acl_manager.check_access(source_node, key_expr, "put")

    result = {
        "source_node": source_node,
        "key_expr": key_expr,
        "authorized": authorized,
    }

    if not authorized:
        policy = _acl_manager.get_policy(source_node)
        allowed = policy.allowed_key_exprs if policy else []
        ids_alerts = _ids_engine.check_acl(
            source_node, key_expr, allowed,
        )
        result["ids_alerts"] = len(ids_alerts)

    return {
        "content": [{
            "type": "text",
            "text": json.dumps(result),
        }]
    }


@tool(
    "security_register_node",
    "Register a node with the ACL manager and derive its HMAC key. "
    "Roles: COORDINATOR, SENSOR_NODE, ACTUATOR_NODE, MIXED_NODE, DIAGNOSTIC.",
    {
        "node_id": str,
        "zone": str,
        "role": str,
    },
)
async def security_register_node(args: dict[str, Any]) -> dict[str, Any]:
    _init_security_stack()
    node_id = args["node_id"]
    zone = args["zone"]
    role = NodeSecurityRole(args["role"])

    _acl_manager.add_node(node_id, zone, role)
    node_key = _get_node_key(node_id)

    allowed = _acl_manager.get_allowed_key_exprs(node_id)

    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "status": "registered",
                "node_id": node_id,
                "zone": zone,
                "role": role.value,
                "key_derived": True,
                "key_id": node_id,
                "allowed_key_exprs": allowed,
            }),
        }]
    }


@tool(
    "security_get_alerts",
    "Get recent IDS alerts from the current simulation session. "
    "Optionally filter by rule_id or severity.",
    {
        "filter_rule": str,
        "max_count": int,
    },
)
async def security_get_alerts(args: dict[str, Any]) -> dict[str, Any]:
    _init_security_stack()
    filter_rule = args.get("filter_rule", "")
    max_count = args.get("max_count", 50)

    alerts = _alerts_history
    if filter_rule:
        alerts = [a for a in alerts if a.get("rule_id") == filter_rule]

    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "total": len(alerts),
                "alerts": alerts[-max_count:],
                "chain_valid": _security_log.verify_chain() if _security_log else None,
            }),
        }]
    }


@tool(
    "security_verify_chain",
    "Verify the integrity of the security event log chain hash. "
    "Returns True if no tampering detected.",
    {},
)
async def security_verify_chain(args: dict[str, Any]) -> dict[str, Any]:
    _init_security_stack()
    valid = _security_log.verify_chain()
    events = _security_log.read_events(last_n=5)

    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "chain_valid": valid,
                "total_events": _security_log.current_seq,
                "recent_events": len(events),
            }),
        }]
    }


def get_all_tools():
    """Return all security tools for MCP server creation."""
    return [
        security_secoc_encode,
        security_secoc_decode,
        security_ids_check,
        security_acl_check,
        security_register_node,
        security_get_alerts,
        security_verify_chain,
    ]
