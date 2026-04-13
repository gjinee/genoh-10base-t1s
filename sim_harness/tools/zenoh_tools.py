"""Zenoh simulation MCP tools.

Simulates Zenoh pub/sub/query operations for the 10BASE-T1S network.
These tools maintain an in-memory message store that mimics a Zenoh session.
"""

from __future__ import annotations

import json
import time
from typing import Any

from claude_agent_sdk import tool

# In-memory simulated Zenoh state
_published_messages: dict[str, list[dict]] = {}
_subscriptions: dict[str, list[str]] = {}
_queryable_endpoints: dict[str, dict] = {}
_active_nodes: dict[str, dict] = {}


def _timestamp_ms() -> int:
    return int(time.time() * 1000)


def _match_key_expr(pattern: str, key: str) -> bool:
    """Simple Zenoh key expression wildcard matching.

    Supports:
      * — matches a single chunk (between slashes)
      ** — matches any number of chunks
    """
    pat_parts = pattern.split("/")
    key_parts = key.split("/")

    pi = ki = 0
    while pi < len(pat_parts) and ki < len(key_parts):
        if pat_parts[pi] == "**":
            if pi == len(pat_parts) - 1:
                return True
            pi += 1
            while ki < len(key_parts):
                if _match_key_expr("/".join(pat_parts[pi:]), "/".join(key_parts[ki:])):
                    return True
                ki += 1
            return False
        elif pat_parts[pi] == "*" or pat_parts[pi] == key_parts[ki]:
            pi += 1
            ki += 1
        else:
            return False
    return pi == len(pat_parts) and ki == len(key_parts)


@tool(
    "zenoh_publish",
    "Publish a message to a Zenoh key expression. "
    "Simulates a Zenoh put operation on the 10BASE-T1S network.",
    {
        "key_expr": str,
        "payload": str,
        "encoding": str,
    },
)
async def zenoh_publish(args: dict[str, Any]) -> dict[str, Any]:
    key_expr = args["key_expr"]
    payload = args.get("payload", "{}")
    encoding = args.get("encoding", "application/json")

    msg = {
        "key_expr": key_expr,
        "payload": payload,
        "encoding": encoding,
        "timestamp": _timestamp_ms(),
    }

    if key_expr not in _published_messages:
        _published_messages[key_expr] = []
    _published_messages[key_expr].append(msg)

    # Keep only last 100 messages per key
    if len(_published_messages[key_expr]) > 100:
        _published_messages[key_expr] = _published_messages[key_expr][-100:]

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "status": "published",
                        "key_expr": key_expr,
                        "timestamp": msg["timestamp"],
                        "encoding": encoding,
                    }
                ),
            }
        ]
    }


@tool(
    "zenoh_subscribe",
    "Subscribe to a Zenoh key expression pattern and retrieve recent messages. "
    "Supports wildcards: * (single level) and ** (multi-level).",
    {
        "key_expr": str,
        "max_messages": int,
    },
)
async def zenoh_subscribe(args: dict[str, Any]) -> dict[str, Any]:
    pattern = args["key_expr"]
    max_msgs = args.get("max_messages", 10)

    matched: list[dict] = []
    for key, messages in _published_messages.items():
        if _match_key_expr(pattern, key):
            matched.extend(messages)

    # Sort by timestamp descending, limit
    matched.sort(key=lambda m: m["timestamp"], reverse=True)
    matched = matched[:max_msgs]

    # Track subscription
    sub_id = f"sub_{_timestamp_ms()}"
    if pattern not in _subscriptions:
        _subscriptions[pattern] = []
    _subscriptions[pattern].append(sub_id)

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "subscription_id": sub_id,
                        "pattern": pattern,
                        "message_count": len(matched),
                        "messages": matched,
                    }
                ),
            }
        ]
    }


@tool(
    "zenoh_query",
    "Send a query to a Zenoh Queryable endpoint and get a reply. "
    "Simulates the Zenoh get() operation for node status queries.",
    {
        "key_expr": str,
        "parameters": str,
    },
)
async def zenoh_query(args: dict[str, Any]) -> dict[str, Any]:
    key_expr = args["key_expr"]
    parameters = args.get("parameters", "")

    # Check if there's a registered queryable
    for qkey, qdata in _queryable_endpoints.items():
        if _match_key_expr(qkey, key_expr) or _match_key_expr(key_expr, qkey):
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "status": "reply",
                                "key_expr": qkey,
                                "reply": qdata,
                                "parameters": parameters,
                            }
                        ),
                    }
                ]
            }

    # Check active nodes for status queries
    parts = key_expr.split("/")
    if len(parts) >= 4 and parts[-1] == "status":
        node_id = parts[-2]
        if node_id in _active_nodes:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "status": "reply",
                                "key_expr": key_expr,
                                "reply": _active_nodes[node_id],
                            }
                        ),
                    }
                ]
            }

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "status": "timeout",
                        "key_expr": key_expr,
                        "message": "No queryable endpoint found for this key expression",
                    }
                ),
            }
        ]
    }


@tool(
    "zenoh_list_nodes",
    "List all active Zenoh nodes on the 10BASE-T1S network. "
    "Returns node IDs, zones, roles, and connection status.",
    {},
)
async def zenoh_list_nodes(args: dict[str, Any]) -> dict[str, Any]:
    nodes = []
    for node_id, info in _active_nodes.items():
        nodes.append(
            {
                "node_id": node_id,
                "zone": info.get("zone", "unknown"),
                "role": info.get("role", "unknown"),
                "plca_id": info.get("plca_node_id", -1),
                "alive": info.get("alive", False),
                "uptime_sec": info.get("uptime_sec", 0),
            }
        )
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "node_count": len(nodes),
                        "nodes": nodes,
                    }
                ),
            }
        ]
    }


@tool(
    "zenoh_register_node",
    "Register a simulated slave node on the Zenoh network. "
    "Creates a liveliness token and makes the node queryable.",
    {
        "node_id": str,
        "zone": str,
        "role": str,
        "plca_node_id": int,
    },
)
async def zenoh_register_node(args: dict[str, Any]) -> dict[str, Any]:
    node_id = args["node_id"]
    zone = args["zone"]
    role = args["role"]
    plca_node_id = args["plca_node_id"]

    node_info = {
        "node_id": node_id,
        "zone": zone,
        "role": role,
        "plca_node_id": plca_node_id,
        "alive": True,
        "uptime_sec": 0,
        "firmware_version": "1.0.0-sim",
        "error_count": 0,
        "tx_count": 0,
        "rx_count": 0,
        "registered_at": _timestamp_ms(),
    }
    _active_nodes[node_id] = node_info

    # Register queryable for status
    status_key = f"vehicle/{zone}/{node_id}/status"
    _queryable_endpoints[status_key] = node_info

    # Publish liveliness token
    alive_key = f"vehicle/{zone}/{node_id}/alive"
    await zenoh_publish(
        {"key_expr": alive_key, "payload": json.dumps({"alive": True})}
    )

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "status": "registered",
                        "node_id": node_id,
                        "plca_node_id": plca_node_id,
                        "liveliness_key": alive_key,
                        "queryable_key": status_key,
                    }
                ),
            }
        ]
    }


def get_all_tools():
    """Return all Zenoh tools for MCP server creation."""
    return [
        zenoh_publish,
        zenoh_subscribe,
        zenoh_query,
        zenoh_list_nodes,
        zenoh_register_node,
    ]
