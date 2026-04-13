"""Node manager with Zenoh Liveliness-based discovery.

Implements PRD FR-006: Node management and discovery.

Uses Zenoh Liveliness tokens for automatic online/offline detection:
- Slave nodes declare: z_liveliness_declare_token("vehicle/{zone}/{node_id}/alive")
- Master subscribes: session.liveliness().declare_subscriber("vehicle/*/*/alive")
- PUT event → node online, DELETE event → node offline
- Initial snapshot: session.liveliness().get("vehicle/*/*/alive")

No separate heartbeat needed — Zenoh transport session keepalive handles it.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import zenoh

from src.common import key_expressions as ke
from src.common.models import NodeInfo, NodeRole, NodeStatus

logger = logging.getLogger(__name__)


class NodeManager:
    """Manages slave node registration, discovery, and health tracking.

    Uses Zenoh Liveliness protocol for automatic node presence detection.
    Maintains an internal registry mapping node_id → NodeInfo with PLCA ID.
    """

    def __init__(self, session: zenoh.Session) -> None:
        self._session = session
        self._nodes: dict[str, NodeInfo] = {}
        self._lock = threading.Lock()
        self._liveliness_sub = None
        self._on_node_online: Callable[[NodeInfo], None] | None = None
        self._on_node_offline: Callable[[NodeInfo], None] | None = None

    @property
    def nodes(self) -> dict[str, NodeInfo]:
        """Current node registry (read-only snapshot)."""
        with self._lock:
            return dict(self._nodes)

    @property
    def online_nodes(self) -> list[NodeInfo]:
        """List of currently online nodes."""
        with self._lock:
            return [n for n in self._nodes.values() if n.alive]

    @property
    def node_count(self) -> int:
        """Total number of registered nodes."""
        with self._lock:
            return len(self._nodes)

    @property
    def online_count(self) -> int:
        """Number of currently online nodes."""
        with self._lock:
            return sum(1 for n in self._nodes.values() if n.alive)

    # --- Node registry ---

    def register_node(
        self,
        node_id: str,
        zone: str,
        plca_node_id: int,
        role: NodeRole = NodeRole.MIXED,
    ) -> NodeInfo:
        """Manually register a known node (e.g., from scenario config)."""
        node = NodeInfo(
            node_id=node_id,
            zone=zone,
            plca_node_id=plca_node_id,
            role=role,
            alive=False,
        )
        with self._lock:
            self._nodes[node_id] = node
        logger.info(
            "Registered node %s (zone=%s, plca_id=%d, role=%s)",
            node_id, zone, plca_node_id, role.value,
        )
        return node

    def get_node(self, node_id: str) -> NodeInfo | None:
        """Get node info by ID."""
        with self._lock:
            return self._nodes.get(node_id)

    def get_node_by_plca_id(self, plca_id: int) -> NodeInfo | None:
        """Get node info by PLCA Node ID."""
        with self._lock:
            for node in self._nodes.values():
                if node.plca_node_id == plca_id:
                    return node
        return None

    # --- Zenoh Liveliness discovery ---

    def start_discovery(
        self,
        on_online: Callable[[NodeInfo], None] | None = None,
        on_offline: Callable[[NodeInfo], None] | None = None,
    ) -> None:
        """Start liveliness-based node discovery.

        PRD FR-006:
        - Subscribe to vehicle/*/*/alive for PUT (online) and DELETE (offline) events
        - Query existing liveliness tokens for initial snapshot

        Args:
            on_online: Callback when a node comes online.
            on_offline: Callback when a node goes offline.
        """
        self._on_node_online = on_online
        self._on_node_offline = on_offline

        pattern = ke.all_alive_pattern()
        logger.info("Starting liveliness discovery: %s", pattern)

        # Subscribe to liveliness changes
        self._liveliness_sub = self._session.liveliness().declare_subscriber(
            pattern, self._on_liveliness_event, history=True
        )

        # Query current liveliness tokens for initial snapshot
        self._query_initial_liveliness(pattern)

    def _on_liveliness_event(self, sample: zenoh.Sample) -> None:
        """Handle a liveliness PUT (online) or DELETE (offline) event."""
        key = str(sample.key_expr)
        parsed = ke.parse_key_expr(key)
        if not parsed or "node_id" not in parsed:
            return

        node_id = parsed["node_id"]
        zone = parsed["zone"]

        if sample.kind == zenoh.SampleKind.PUT:
            self._handle_node_online(node_id, zone)
        elif sample.kind == zenoh.SampleKind.DELETE:
            self._handle_node_offline(node_id)

    def _handle_node_online(self, node_id: str, zone: str) -> None:
        """Mark a node as online (liveliness PUT received)."""
        with self._lock:
            if node_id in self._nodes:
                node = self._nodes[node_id]
                node.alive = True
                node.last_seen_ms = int(time.time() * 1000)
            else:
                # Auto-register previously unknown node
                node = NodeInfo(
                    node_id=node_id,
                    zone=zone,
                    plca_node_id=-1,  # Unknown until queried
                    alive=True,
                )
                self._nodes[node_id] = node

        logger.info("Node ONLINE: %s (zone=%s)", node_id, zone)
        if self._on_node_online:
            self._on_node_online(node)

    def _handle_node_offline(self, node_id: str) -> None:
        """Mark a node as offline (liveliness DELETE received).

        PRD error handling: "노드 오프라인 표시 → 로그 기록 → 재연결 시 자동 복구"
        """
        with self._lock:
            if node_id in self._nodes:
                self._nodes[node_id].alive = False

        logger.warning("Node OFFLINE: %s", node_id)
        node = self._nodes.get(node_id)
        if node and self._on_node_offline:
            self._on_node_offline(node)

    def _query_initial_liveliness(self, pattern: str) -> None:
        """Query existing liveliness tokens for initial node snapshot.

        PRD FR-006: "초기 상태 조회: z_liveliness_get()"
        """
        logger.info("Querying initial liveliness tokens: %s", pattern)
        try:
            replies = self._session.liveliness().get(pattern, timeout=5.0)
            for reply in replies:
                try:
                    key = str(reply.ok.key_expr)
                    parsed = ke.parse_key_expr(key)
                    if parsed and "node_id" in parsed:
                        self._handle_node_online(parsed["node_id"], parsed["zone"])
                except Exception as e:
                    logger.debug("Skipping liveliness reply: %s", e)
        except Exception as e:
            logger.warning("Initial liveliness query failed: %s", e)

    def stop_discovery(self) -> None:
        """Stop liveliness discovery."""
        if self._liveliness_sub:
            self._liveliness_sub.undeclare()
            self._liveliness_sub = None
            logger.info("Liveliness discovery stopped")

    # --- PLCA ID mapping ---

    def get_plca_mapping(self) -> dict[int, str]:
        """Get PLCA Node ID → node_id mapping table."""
        with self._lock:
            return {
                n.plca_node_id: n.node_id
                for n in self._nodes.values()
                if n.plca_node_id >= 0
            }
