"""Zenoh session manager for the master node.

Implements PRD FR-002 through FR-005 using the real eclipse-zenoh Python API.
Connects as a client to the local zenohd router (tcp/127.0.0.1:7447).

Architecture (PRD Section 2.4):
  ┌─────────────┐    ┌───────────────────┐
  │   zenohd    │◄───│  Master App       │
  │  (Router)   │    │  (this module)    │
  │ tcp/*:7447  │    │  mode: client     │
  └──────┬──────┘    └───────────────────┘
         │
   10BASE-T1S Bus ── Slave(zenoh-pico client)
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

import zenoh

from src.common import key_expressions as ke
from src.common import payloads
from src.common.models import ActuatorCommand, SensorData

logger = logging.getLogger(__name__)


class ZenohMaster:
    """Manages the Zenoh session for the master controller.

    Opens a Zenoh session in client mode connecting to the local zenohd router.
    Provides pub/sub/query operations for sensor data collection, actuator
    control, and node status queries.
    """

    def __init__(
        self,
        router_endpoint: str = "tcp/127.0.0.1:7447",
        encoding: str = payloads.ENCODING_JSON,
    ) -> None:
        self._router_endpoint = router_endpoint
        self._encoding = encoding
        self._session: zenoh.Session | None = None
        self._subscribers: list = []
        self._publishers: dict[str, Any] = {}
        self._queryables: list = []
        self._sensor_callbacks: list[Callable] = []

    # --- Session lifecycle ---

    def open(self) -> None:
        """Open a Zenoh session in client mode.

        PRD Section 2.4: Python app connects as client to local zenohd
        via TCP loopback (tcp/127.0.0.1:7447).
        """
        zenoh.init_log_from_env_or("error")

        conf = zenoh.Config()
        conf.insert_json5("mode", '"client"')
        conf.insert_json5("connect/endpoints", json.dumps([self._router_endpoint]))

        logger.info("Opening Zenoh session (client mode) → %s", self._router_endpoint)
        self._session = zenoh.open(conf)
        logger.info("Zenoh session opened: %s", self._session.zid())

    def close(self) -> None:
        """Close the Zenoh session and all declared resources."""
        if self._session:
            logger.info("Closing Zenoh session")
            # Undeclare publishers
            for pub in self._publishers.values():
                pub.undeclare()
            self._publishers.clear()
            self._session.close()
            self._session = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    @property
    def session(self) -> zenoh.Session:
        if self._session is None:
            raise RuntimeError("Zenoh session not open — call open() first")
        return self._session

    # --- FR-003: Sensor data subscribe ---

    def subscribe_sensors(
        self,
        zone: str = "*",
        sensor_type: str = "*",
        callback: Callable[[str, SensorData], None] | None = None,
    ) -> None:
        """Subscribe to sensor data from slave nodes.

        PRD FR-003: Subscribe to vehicle/{zone}/{node_id}/sensor/{type}

        Args:
            zone: Zone filter ("*" for all zones).
            sensor_type: Sensor type filter ("*" for all types).
            callback: Called with (key_expr, SensorData) for each message.
        """
        pattern = ke.all_sensors_pattern(zone=zone, sensor_type=sensor_type)
        logger.info("Subscribing to sensors: %s", pattern)

        def _on_sensor(sample: zenoh.Sample):
            key = str(sample.key_expr)
            try:
                data_dict = payloads.decode(sample.payload.to_bytes())
                sensor_data = SensorData.from_dict(data_dict)
                logger.debug("Sensor data: %s → %s", key, sensor_data)
                if callback:
                    callback(key, sensor_data)
            except Exception as e:
                logger.error("Failed to decode sensor data from %s: %s", key, e)

        sub = self.session.declare_subscriber(pattern, _on_sensor)
        self._subscribers.append(sub)

    # --- FR-004: Actuator command publish ---

    def publish_actuator(
        self,
        zone: str,
        node_id: int | str,
        actuator_type: str,
        command: ActuatorCommand,
    ) -> None:
        """Publish an actuator command to a slave node.

        PRD FR-004: Publish to vehicle/{zone}/{node_id}/actuator/{type}

        Args:
            zone: Target zone.
            node_id: Target node ID (1-7).
            actuator_type: Actuator type (led, motor, relay, buzzer, lock).
            command: ActuatorCommand with action and params.
        """
        key = ke.actuator_key(zone, node_id, actuator_type)
        payload_bytes = payloads.encode(command.to_dict(), self._encoding)

        # Reuse publisher or create new one
        if key not in self._publishers:
            self._publishers[key] = self.session.declare_publisher(key)

        self._publishers[key].put(payload_bytes)
        logger.info("Published actuator command: %s → %s", key, command.action)

    def put(self, key_expr: str, data: dict) -> None:
        """Direct put to any key expression."""
        payload_bytes = payloads.encode(data, self._encoding)
        self.session.put(key_expr, payload_bytes)

    # --- FR-005: Node status query ---

    def query_node_status(
        self,
        zone: str,
        node_id: int | str,
        timeout_sec: float = 5.0,
    ) -> dict | None:
        """Query a slave node's status via Zenoh Queryable.

        PRD FR-005: Query vehicle/{zone}/{node_id}/status

        Returns the parsed status dict or None on timeout.
        """
        key = ke.status_key(zone, node_id)
        logger.info("Querying node status: %s", key)

        replies = self.session.get(key, timeout=timeout_sec)
        for reply in replies:
            try:
                payload_str = reply.ok.payload.to_string()
                return payloads.decode(payload_str)
            except Exception as e:
                logger.error("Failed to decode status reply from %s: %s", key, e)
                return None

        logger.warning("Status query timeout for %s", key)
        return None

    # --- Master heartbeat & diagnostics ---

    def publish_heartbeat(self, uptime_sec: int, node_count: int) -> None:
        """Publish master heartbeat on vehicle/master/heartbeat."""
        data = {
            "alive": True,
            "uptime_sec": uptime_sec,
            "node_count": node_count,
            "ts": int(time.time() * 1000),
        }
        self.put(ke.MASTER_HEARTBEAT, data)

    def publish_diagnostics(self, diagnostics: dict) -> None:
        """Publish diagnostics data on vehicle/master/diagnostics."""
        diagnostics["ts"] = int(time.time() * 1000)
        self.put(ke.MASTER_DIAGNOSTICS, diagnostics)

    # --- Queryable (master responds to queries) ---

    def declare_queryable(
        self,
        key_expr: str,
        handler: Callable[[Any], dict],
    ) -> None:
        """Declare a Queryable endpoint on the master.

        The handler receives the query and returns a dict to be sent as reply.
        """
        queryable = self.session.declare_queryable(key_expr)
        self._queryables.append((queryable, handler, key_expr))
        logger.info("Declared queryable: %s", key_expr)

    def process_queries(self, timeout_sec: float = 0.1) -> None:
        """Process pending queries on all declared queryables (non-blocking)."""
        for queryable, handler, key_expr in self._queryables:
            try:
                query = queryable.try_recv()
                if query is not None:
                    reply_data = handler(query)
                    reply_bytes = payloads.encode(reply_data, self._encoding)
                    query.reply(key_expr, reply_bytes)
            except Exception:
                pass  # No pending query
