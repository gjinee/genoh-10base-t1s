"""PLCA simulation MCP tools.

Simulates PLCA (Physical Layer Collision Avoidance) status and configuration
for the 10BASE-T1S multidrop bus.
"""

from __future__ import annotations

import json
import time
from typing import Any

from claude_agent_sdk import tool

# Simulated PLCA state
_plca_state = {
    "enabled": True,
    "coordinator": True,
    "local_node_id": 0,
    "node_count": 8,
    "to_timer": 0x20,  # 32 bit-times
    "burst_count": 0,
    "burst_timer": 0x80,
    "beacon_active": True,
    "collision_count": 0,
    "cycle_count": 0,
    "interface": "eth1",
    "link_status": "up",
    "speed_mbps": 10,
}


@tool(
    "plca_get_status",
    "Get current PLCA status of the 10BASE-T1S network interface. "
    "Returns beacon state, node count, collision info, and timing parameters.",
    {"interface": str},
)
async def plca_get_status(args: dict[str, Any]) -> dict[str, Any]:
    iface = args.get("interface", "eth1")

    # Simulate cycle progression
    _plca_state["cycle_count"] += 1

    status = {
        "interface": iface,
        "plca_support": "supported",
        "plca_status": "enabled" if _plca_state["enabled"] else "disabled",
        "coordinator": _plca_state["coordinator"],
        "local_node_id": _plca_state["local_node_id"],
        "node_count": _plca_state["node_count"],
        "to_timer_bit_times": _plca_state["to_timer"],
        "beacon_active": _plca_state["beacon_active"],
        "link_status": _plca_state["link_status"],
        "speed_mbps": _plca_state["speed_mbps"],
        "collision_count": _plca_state["collision_count"],
        "cycle_count": _plca_state["cycle_count"],
        "worst_case_cycle_ms": _calculate_worst_case_ms(_plca_state["node_count"]),
        "min_cycle_us": _calculate_min_cycle_us(
            _plca_state["node_count"], _plca_state["to_timer"]
        ),
        "timestamp": int(time.time() * 1000),
    }

    return {
        "content": [{"type": "text", "text": json.dumps(status)}]
    }


@tool(
    "plca_set_config",
    "Configure PLCA parameters for the 10BASE-T1S interface. "
    "Simulates ethtool --set-plca-cfg command.",
    {
        "interface": str,
        "enable": bool,
        "node_id": int,
        "node_count": int,
        "to_timer": int,
    },
)
async def plca_set_config(args: dict[str, Any]) -> dict[str, Any]:
    iface = args.get("interface", "eth1")
    errors = []

    if "enable" in args:
        _plca_state["enabled"] = args["enable"]

    if "node_id" in args:
        nid = args["node_id"]
        if not 0 <= nid <= 255:
            errors.append(f"Invalid node_id {nid}: must be 0-255")
        else:
            _plca_state["local_node_id"] = nid
            _plca_state["coordinator"] = nid == 0

    if "node_count" in args:
        ncnt = args["node_count"]
        if not 1 <= ncnt <= 255:
            errors.append(f"Invalid node_count {ncnt}: must be 1-255")
        elif ncnt > 8:
            errors.append(
                f"Warning: node_count {ncnt} exceeds recommended max of 8 for 10BASE-T1S"
            )
        _plca_state["node_count"] = min(ncnt, 255)

    if "to_timer" in args:
        _plca_state["to_timer"] = args["to_timer"]

    # Beacon only active if coordinator and enabled
    _plca_state["beacon_active"] = (
        _plca_state["enabled"] and _plca_state["coordinator"]
    )

    if errors:
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"status": "warning", "errors": errors, "applied": True}
                    ),
                }
            ]
        }

    equivalent_cmd = (
        f"sudo ethtool --set-plca-cfg {iface}"
        f" enable {'on' if _plca_state['enabled'] else 'off'}"
        f" node-id {_plca_state['local_node_id']}"
        f" node-cnt {_plca_state['node_count']}"
        f" to-timer {_plca_state['to_timer']}"
    )

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "status": "configured",
                        "interface": iface,
                        "equivalent_command": equivalent_cmd,
                        "config": {
                            "enabled": _plca_state["enabled"],
                            "coordinator": _plca_state["coordinator"],
                            "node_id": _plca_state["local_node_id"],
                            "node_count": _plca_state["node_count"],
                            "to_timer": _plca_state["to_timer"],
                        },
                    }
                ),
            }
        ]
    }


def _calculate_worst_case_ms(node_count: int) -> float:
    """Calculate worst-case PLCA cycle time in ms (all nodes max frame)."""
    beacon_bits = 20
    frame_bits = 1518 * 8  # max Ethernet frame
    total_bits = beacon_bits + (node_count * frame_bits)
    return round(total_bits / 10_000_000 * 1000, 2)  # 10 MHz


def _calculate_min_cycle_us(node_count: int, to_timer: int) -> float:
    """Calculate minimum PLCA cycle time in us (all nodes idle)."""
    beacon_bits = 20
    total_bits = beacon_bits + (node_count * to_timer)
    return round(total_bits / 10_000_000 * 1_000_000, 1)  # 10 MHz


def get_all_tools():
    """Return all PLCA tools for MCP server creation."""
    return [plca_get_status, plca_set_config]
