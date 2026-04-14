"""Simulation engine bridging Zenoh sessions (real or simulated) with GUI.

Runs as a background task, generating sensor data, processing commands,
managing safety/security state, and pushing events to WebSocket clients.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import random
import struct
import time
import zlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from gui.common.protocol import MsgType, WSMessage
from gui.common.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)

SCENARIOS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "scenarios"


# ---------------------------------------------------------------------------
# E2E Protection helpers
# ---------------------------------------------------------------------------

def e2e_encode(payload_bytes: bytes, data_id: int, seq: int) -> bytes:
    """Encode with CRC-32 + 16-bit sequence counter."""
    header = struct.pack(">HH", data_id & 0xFFFF, seq & 0xFFFF)
    body = header + payload_bytes
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return body + struct.pack(">I", crc)


def e2e_decode(raw: bytes) -> tuple[bytes, int, int, bool]:
    """Decode E2E. Returns (payload, data_id, seq, crc_ok)."""
    if len(raw) < 8:
        return raw, 0, 0, False
    stored_crc = struct.unpack(">I", raw[-4:])[0]
    body = raw[:-4]
    computed = zlib.crc32(body) & 0xFFFFFFFF
    data_id, seq = struct.unpack(">HH", body[:4])
    return body[4:], data_id, seq, stored_crc == computed


# ---------------------------------------------------------------------------
# SecOC helpers
# ---------------------------------------------------------------------------

def secoc_mac(payload: bytes, key: bytes) -> str:
    return hashlib.sha256(key + payload).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class SafetyState(str, Enum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    SAFE_STATE = "SAFE_STATE"
    FAIL_SILENT = "FAIL_SILENT"


@dataclass
class SimNode:
    node_id: str
    zone: str
    plca_id: int
    role: str  # sensor / actuator / mixed
    alive: bool = True
    sensors: dict[str, float] = field(default_factory=dict)
    actuators: dict[str, dict] = field(default_factory=dict)
    tx_count: int = 0
    rx_count: int = 0
    error_count: int = 0
    seq_counter: int = 0
    e2e_ok: int = 0
    e2e_fail: int = 0
    secoc_ok: int = 0
    secoc_fail: int = 0
    registered_at: float = field(default_factory=time.time)

    @property
    def uptime(self) -> float:
        return time.time() - self.registered_at


@dataclass
class IDSAlertRecord:
    rule_id: str
    severity: str
    source_node: str
    description: str
    ts: float = field(default_factory=time.time)


class SimEngine:
    """Core simulation engine shared by master and slave GUIs."""

    def __init__(self, mode: str = "sim") -> None:
        self.mode = mode  # "sim" or "hw"
        self.running = False

        # Node registry
        self.nodes: dict[str, SimNode] = {}

        # Safety state
        self.safety_state = SafetyState.NORMAL
        self.safety_prev = SafetyState.NORMAL
        self.watchdog_last_kick = time.time()
        self.watchdog_timeout = 5.0
        self.flow_checkpoints: list[str] = []
        self.dtc_active: list[dict] = []

        # Security
        self.ids_alerts: list[IDSAlertRecord] = []
        self.security_log: list[dict] = []
        self.master_key = b"zenoh-10base-t1s-master-secret-key-v1"

        # PLCA
        self.plca_beacon_active = True
        self.plca_node_count = 1  # master only at start
        self.plca_collisions = 0

        # Message bus (in-memory for sim mode)
        self.message_log: list[dict] = []
        self.bus_messages: list[dict] = []

        # Scenario
        self.scenario_name: str = ""
        self.scenario_data: dict = {}
        self.scenario_step_idx: int = 0

        # Callbacks
        self._master_mgr: ConnectionManager | None = None
        self._slave_mgr: ConnectionManager | None = None

        # Agent logs
        self.agent_logs: list[dict] = []

        # Real Zenoh session (HW mode only)
        self._zenoh_session = None
        self._zenoh_subscribers: list = []

        # ns_slave child processes (HW mode, auto-launched)
        self._slave_procs: list = []

    def set_managers(
        self,
        master: ConnectionManager | None = None,
        slave: ConnectionManager | None = None,
    ) -> None:
        if master is not None:
            self._master_mgr = master
        if slave is not None:
            self._slave_mgr = slave

    # ------------------------------------------------------------------
    # Zenoh session (HW mode)
    # ------------------------------------------------------------------

    def _open_zenoh(self) -> None:
        """Open a real Zenoh session for HW mode."""
        if self._zenoh_session is not None:
            return
        try:
            import zenoh
            cfg = zenoh.Config()
            # Connect to zenohd router via 10BASE-T1S interface IP
            # (192.168.1.1 = eth1 bound to EVB-LAN8670-USB)
            cfg.insert_json5("mode", '"client"')
            cfg.insert_json5("connect/endpoints", '["tcp/192.168.1.1:7447"]')
            cfg.insert_json5("scouting/multicast/enabled", "false")
            self._zenoh_session = zenoh.open(cfg)
            logger.info("Zenoh HW session opened: zid=%s", self._zenoh_session.zid())
        except Exception as e:
            logger.error("Failed to open Zenoh session: %s", e)
            self._zenoh_session = None

    def _close_zenoh(self) -> None:
        """Close the Zenoh session."""
        for sub in self._zenoh_subscribers:
            try:
                sub.undeclare()
            except Exception:
                pass
        self._zenoh_subscribers.clear()
        if self._zenoh_session is not None:
            try:
                self._zenoh_session.close()
            except Exception:
                pass
            self._zenoh_session = None
            logger.info("Zenoh HW session closed")

    def _launch_ns_slave_nodes(self) -> None:
        """Auto-launch zenoh-pico nodes in ns_slave network namespace.

        These create real 10BASE-T1S bus traffic (192.168.1.2 ↔ 192.168.1.1)
        so that Wireshark can capture Zenoh frames on eth1.
        Without these, all traffic stays on loopback (same-host).
        """
        import subprocess

        build_dir = Path(__file__).resolve().parent.parent.parent / "slave_examples" / "build"
        sensor_bin = build_dir / "sensor_node"
        actuator_bin = build_dir / "actuator_node"

        # Check ns_slave namespace exists
        try:
            subprocess.run(
                ["ip", "netns", "list"], capture_output=True, check=True,
            )
        except Exception:
            logger.warning("ip netns not available, skipping ns_slave launch")
            return

        zone = self.scenario_data.get("zone", "front_left") if self.scenario_data else "front_left"
        endpoint = "tcp/192.168.1.1:7447"

        if sensor_bin.exists():
            try:
                p = subprocess.Popen(
                    ["sudo", "ip", "netns", "exec", "ns_slave",
                     str(sensor_bin), zone, "6", endpoint],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                self._slave_procs.append(p)
                logger.info("ns_slave sensor_node launched (PID %d, PLCA 6)", p.pid)
            except Exception as e:
                logger.error("Failed to launch ns_slave sensor_node: %s", e)

        if actuator_bin.exists():
            try:
                p = subprocess.Popen(
                    ["sudo", "ip", "netns", "exec", "ns_slave",
                     str(actuator_bin), zone, "7", endpoint],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                self._slave_procs.append(p)
                logger.info("ns_slave actuator_node launched (PID %d, PLCA 7)", p.pid)
            except Exception as e:
                logger.error("Failed to launch ns_slave actuator_node: %s", e)

    def _stop_ns_slave_nodes(self) -> None:
        """Terminate all ns_slave child processes."""
        import subprocess
        for p in self._slave_procs:
            try:
                p.terminate()
                p.wait(timeout=3)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
            logger.info("ns_slave process (PID %d) stopped", p.pid)
        self._slave_procs.clear()
        # Also kill any orphaned sensor_node/actuator_node in ns_slave
        subprocess.run(
            ["sudo", "ip", "netns", "exec", "ns_slave", "pkill", "-f", "sensor_node"],
            capture_output=True,
        )
        subprocess.run(
            ["sudo", "ip", "netns", "exec", "ns_slave", "pkill", "-f", "actuator_node"],
            capture_output=True,
        )

    def _zenoh_put(self, key_expr: str, payload_bytes: bytes) -> bool:
        """Publish via real Zenoh session. Returns True on success."""
        if self._zenoh_session is None:
            return False
        try:
            self._zenoh_session.put(key_expr, payload_bytes)
            return True
        except Exception as e:
            logger.error("Zenoh put failed [%s]: %s", key_expr, e)
            return False

    def _zenoh_subscribe_all(self, loop: asyncio.AbstractEventLoop) -> None:
        """Subscribe to vehicle/** on real Zenoh to capture incoming messages."""
        if self._zenoh_session is None:
            return
        try:
            import zenoh

            def _on_sample(sample) -> None:
                """Called from Zenoh background thread on each received message."""
                ke = str(sample.key_expr)
                payload_bytes = bytes(sample.payload)
                ts_now = time.time()

                bus_msg = {
                    "direction": "SUB",
                    "key_expr": ke,
                    "payload_size": len(payload_bytes),
                    "ts": ts_now,
                }
                self.bus_messages.append(bus_msg)
                if len(self.bus_messages) > 500:
                    self.bus_messages = self.bus_messages[-500:]

                # Parse sensor data from incoming payload
                parts = ke.split("/")
                if "sensor" in parts:
                    try:
                        # Try to E2E-decode
                        inner, data_id, seq, crc_ok = e2e_decode(payload_bytes)
                        body = json.loads(inner.decode())
                        idx = parts.index("sensor")
                        stype = parts[idx + 1] if idx + 1 < len(parts) else "unknown"
                        node_id = parts[idx - 1] if idx > 0 else "?"
                        zone = parts[1] if len(parts) > 1 else ""

                        sensor_msg = {
                            "node_id": node_id,
                            "sensor_type": stype,
                            "value": body.get("value", 0),
                            "unit": body.get("unit", ""),
                            "seq": seq,
                            "crc_ok": crc_ok,
                            "e2e_status": "VALID" if crc_ok else "INVALID",
                            "raw_size": len(payload_bytes),
                        }

                        # Update node state
                        node = self.nodes.get(node_id)
                        if node:
                            node.sensors[stype] = body.get("value", 0)
                            node.rx_count += 1
                            if crc_ok:
                                node.e2e_ok += 1
                            else:
                                node.e2e_fail += 1

                        # Schedule GUI broadcast on the event loop
                        asyncio.run_coroutine_threadsafe(
                            self._broadcast_all(WSMessage(
                                type=MsgType.SENSOR_DATA,
                                source="hw_bus",
                                payload=sensor_msg,
                            )),
                            loop,
                        )
                    except Exception:
                        pass

                elif "actuator" in parts:
                    try:
                        body = json.loads(payload_bytes.decode())
                        idx = parts.index("actuator")
                        atype = parts[idx + 1] if idx + 1 < len(parts) else "unknown"
                        node_id = parts[idx - 1] if idx > 0 else "?"

                        act_msg = {
                            "node_id": node_id,
                            "actuator_type": atype,
                            "action": body.get("action", ""),
                            "params": body.get("params", {}),
                            "secoc_status": "RECEIVED",
                        }
                        asyncio.run_coroutine_threadsafe(
                            self._broadcast_all(WSMessage(
                                type=MsgType.ACTUATOR_CMD,
                                source="hw_bus",
                                payload=act_msg,
                            )),
                            loop,
                        )
                    except Exception:
                        pass

            sub = self._zenoh_session.declare_subscriber("vehicle/**", _on_sample)
            self._zenoh_subscribers.append(sub)
            logger.info("Zenoh HW subscriber on vehicle/**")
        except Exception as e:
            logger.error("Zenoh subscribe failed: %s", e)

    async def _broadcast_all(self, msg: WSMessage) -> None:
        """Broadcast a message to both master and slave GUI clients."""
        if self._master_mgr:
            await self._master_mgr.broadcast(msg)
        if self._slave_mgr:
            await self._slave_mgr.broadcast(msg)

    # ------------------------------------------------------------------
    # Node management
    # ------------------------------------------------------------------

    def register_node(self, node_id: str, zone: str, plca_id: int, role: str) -> SimNode:
        node = SimNode(
            node_id=node_id, zone=zone, plca_id=plca_id, role=role
        )
        # Init default sensor values based on role keywords
        role_lower = role.lower()
        has_sensor = role_lower in ("sensor", "mixed") or "sensor" in role_lower
        has_actuator = role_lower in ("actuator", "mixed") or "actuator" in role_lower or "motor" in role_lower
        if has_sensor:
            node.sensors = {"temperature": 25.0, "proximity": 100.0, "battery": 3.7}
        if has_actuator:
            node.actuators = {
                "lock": {"state": "unlock"},
                "motor": {"state": "stop"},
                "led": {"state": "off"},
            }
        self.nodes[node_id] = node
        self.plca_node_count = len(self.nodes) + 1  # +1 for master
        return node

    def remove_node(self, node_id: str) -> None:
        self.nodes.pop(node_id, None)
        self.plca_node_count = len(self.nodes) + 1

    # ------------------------------------------------------------------
    # Sensor simulation
    # ------------------------------------------------------------------

    def generate_sensor_value(self, node_id: str, sensor_type: str) -> float | None:
        node = self.nodes.get(node_id)
        if not node or not node.alive:
            return None
        current = node.sensors.get(sensor_type, 25.0)
        # Realistic drift
        if sensor_type == "temperature":
            drift = random.uniform(-0.5, 0.5)
            new_val = max(-40.0, min(150.0, current + drift))
        elif sensor_type == "proximity":
            drift = random.uniform(-5.0, 5.0)
            new_val = max(0.0, min(500.0, current + drift))
        elif sensor_type == "battery":
            drift = random.uniform(-0.01, 0.005)
            new_val = max(0.0, min(4.2, current + drift))
        else:
            drift = random.uniform(-1.0, 1.0)
            new_val = current + drift
        node.sensors[sensor_type] = round(new_val, 2)
        return node.sensors[sensor_type]

    # ------------------------------------------------------------------
    # E2E + SecOC processing
    # ------------------------------------------------------------------

    def encode_sensor_message(self, node_id: str, sensor_type: str, value: float) -> dict:
        node = self.nodes.get(node_id)
        if not node:
            return {}
        node.seq_counter = (node.seq_counter + 1) & 0xFFFF
        payload = json.dumps({"value": value, "unit": self._unit(sensor_type), "ts": int(time.time() * 1000)})
        raw = e2e_encode(payload.encode(), 0x1001, node.seq_counter)
        node.tx_count += 1
        node.e2e_ok += 1
        return {
            "node_id": node_id,
            "sensor_type": sensor_type,
            "value": value,
            "unit": self._unit(sensor_type),
            "seq": node.seq_counter,
            "crc": zlib.crc32(raw) & 0xFFFFFFFF,
            "e2e_status": "VALID",
            "raw_size": len(raw),
        }

    def encode_actuator_command(self, node_id: str, actuator_type: str, action: str, params: dict) -> dict:
        payload = json.dumps({"action": action, "params": params, "ts": int(time.time() * 1000)})
        key = hashlib.sha256(self.master_key + node_id.encode()).digest()[:16]
        mac = secoc_mac(payload.encode(), key)
        return {
            "node_id": node_id,
            "actuator_type": actuator_type,
            "action": action,
            "params": params,
            "mac": mac,
            "secoc_status": "AUTHENTICATED",
        }

    def _unit(self, sensor_type: str) -> str:
        return {
            "temperature": "celsius",
            "proximity": "cm",
            "battery": "volt",
            "pressure": "kpa",
            "light": "lux",
        }.get(sensor_type, "")

    # ------------------------------------------------------------------
    # Safety FSM
    # ------------------------------------------------------------------

    def transition_safety(self, new_state: SafetyState, reason: str = "") -> dict:
        self.safety_prev = self.safety_state
        self.safety_state = new_state
        event = {
            "state": new_state.value,
            "prev_state": self.safety_prev.value,
            "reason": reason,
            "ts": time.time(),
        }
        logger.info("Safety: %s -> %s (%s)", self.safety_prev.value, new_state.value, reason)
        return event

    def check_watchdog(self) -> bool:
        elapsed = time.time() - self.watchdog_last_kick
        if elapsed > self.watchdog_timeout and self.safety_state != SafetyState.FAIL_SILENT:
            self.transition_safety(SafetyState.SAFE_STATE, "WATCHDOG_EXPIRED")
            return False
        return True

    def kick_watchdog(self) -> float:
        self.watchdog_last_kick = time.time()
        return self.watchdog_timeout

    def report_fault(self, fault_type: str, node_id: str = "") -> dict:
        if fault_type == "NODE_OFFLINE" and node_id:
            node = self.nodes.get(node_id)
            if node:
                node.alive = False
            offline = sum(1 for n in self.nodes.values() if not n.alive)
            total = len(self.nodes)
            if total > 0 and offline / total >= 0.5:
                return self.transition_safety(SafetyState.SAFE_STATE, f">=50% nodes offline ({offline}/{total})")
            elif self.safety_state == SafetyState.NORMAL:
                return self.transition_safety(SafetyState.DEGRADED, f"Node {node_id} offline")
        elif fault_type == "CRC_FAILURE":
            if self.safety_state == SafetyState.NORMAL:
                return self.transition_safety(SafetyState.DEGRADED, "CRC failure detected")
        elif fault_type in ("WATCHDOG_EXPIRED", "FLOW_ERROR"):
            return self.transition_safety(SafetyState.SAFE_STATE, fault_type)
        return {"state": self.safety_state.value, "reason": fault_type}

    # ------------------------------------------------------------------
    # IDS
    # ------------------------------------------------------------------

    def ids_check(self, rule_id: str, source_node: str, description: str, severity: str = "MEDIUM") -> IDSAlertRecord:
        alert = IDSAlertRecord(
            rule_id=rule_id, severity=severity,
            source_node=source_node, description=description,
        )
        self.ids_alerts.append(alert)
        return alert

    # ------------------------------------------------------------------
    # Scenario
    # ------------------------------------------------------------------

    def load_scenario(self, name: str) -> dict:
        import yaml
        path = SCENARIOS_DIR / f"{name}.yaml"
        if not path.exists():
            return {"error": f"Scenario {name} not found"}
        with open(path) as f:
            self.scenario_data = yaml.safe_load(f)
        self.scenario_name = name
        self.scenario_step_idx = 0
        # Register scenario nodes with their publish/subscribe config
        zone = self.scenario_data.get("zone", "default")
        for node_def in self.scenario_data.get("nodes", []):
            node = self.register_node(
                node_id=node_def["node_id"],
                zone=zone,
                plca_id=node_def["plca_node_id"],
                role=node_def["role"],
            )
            # Add sensors from publish config
            for pub in node_def.get("publish", []):
                key = pub.get("key", "")
                parts = key.split("/")
                if "sensor" in parts:
                    idx = parts.index("sensor")
                    if idx + 1 < len(parts):
                        stype = parts[idx + 1]
                        vr = pub.get("value_range", [0, 100])
                        node.sensors[stype] = (vr[0] + vr[1]) / 2.0
            # Add actuators from subscribe config
            for sub in node_def.get("subscribe", []):
                key = sub if isinstance(sub, str) else sub.get("key", "")
                parts = key.split("/")
                if "actuator" in parts:
                    idx = parts.index("actuator")
                    if idx + 1 < len(parts):
                        atype = parts[idx + 1]
                        node.actuators[atype] = {"state": "off"}
        return self.scenario_data

    def list_scenarios(self) -> list[str]:
        if not SCENARIOS_DIR.exists():
            return []
        return [p.stem for p in SCENARIOS_DIR.glob("*.yaml")]

    # ------------------------------------------------------------------
    # State snapshot (for initial GUI load)
    # ------------------------------------------------------------------

    def get_full_state(self) -> dict:
        return {
            "mode": self.mode,
            "running": self.running,
            "safety_state": self.safety_state.value,
            "watchdog_remaining": max(0, self.watchdog_timeout - (time.time() - self.watchdog_last_kick)),
            "plca": {
                "beacon_active": self.plca_beacon_active,
                "node_count": self.plca_node_count,
                "collisions": self.plca_collisions,
            },
            "nodes": {
                nid: {
                    "node_id": n.node_id,
                    "zone": n.zone,
                    "plca_id": n.plca_id,
                    "role": n.role,
                    "alive": n.alive,
                    "sensors": n.sensors,
                    "actuators": n.actuators,
                    "tx_count": n.tx_count,
                    "rx_count": n.rx_count,
                    "error_count": n.error_count,
                    "seq_counter": n.seq_counter,
                    "e2e_ok": n.e2e_ok,
                    "e2e_fail": n.e2e_fail,
                    "secoc_ok": n.secoc_ok,
                    "secoc_fail": n.secoc_fail,
                    "uptime": round(n.uptime, 1),
                }
                for nid, n in self.nodes.items()
            },
            "ids_alert_count": len(self.ids_alerts),
            "dtc_active": self.dtc_active,
            "scenario": self.scenario_name,
            "scenarios_available": self.list_scenarios(),
        }

    # ------------------------------------------------------------------
    # Main simulation loop
    # ------------------------------------------------------------------

    async def run_loop(self) -> None:
        """Main simulation loop — generates sensor data, checks safety, pushes to GUI.

        In HW mode, publishes via real Zenoh session to 10BASE-T1S bus.
        In SIM mode, uses in-memory broadcast only.
        """
        self.running = True
        self.watchdog_last_kick = time.time()
        cycle = 0

        # HW mode: open Zenoh session, subscribe, and launch ns_slave nodes
        if self.mode == "hw":
            self._open_zenoh()
            if self._zenoh_session:
                loop = asyncio.get_running_loop()
                self._zenoh_subscribe_all(loop)
                self._launch_ns_slave_nodes()
                logger.info("HW mode: Zenoh session + ns_slave nodes active, traffic on 10BASE-T1S")
            else:
                logger.warning("HW mode: Zenoh session failed, falling back to SIM-like behavior")

        try:
            while self.running:
                cycle += 1

                # 1. Generate sensor data for all alive nodes
                for node_id, node in list(self.nodes.items()):
                    if not node.alive:
                        continue
                    for stype in list(node.sensors.keys()):
                        value = self.generate_sensor_value(node_id, stype)
                        if value is None:
                            continue
                        msg_data = self.encode_sensor_message(node_id, stype, value)
                        key_expr = f"vehicle/{node.zone}/{node_id}/sensor/{stype}"

                        # HW mode: publish to real Zenoh → 10BASE-T1S bus
                        if self.mode == "hw" and self._zenoh_session:
                            payload_json = json.dumps({
                                "value": value,
                                "unit": self._unit(stype),
                                "ts": int(time.time() * 1000),
                            })
                            e2e_bytes = e2e_encode(
                                payload_json.encode(), 0x1001, node.seq_counter,
                            )
                            self._zenoh_put(key_expr, e2e_bytes)

                        bus_msg = {
                            "direction": "PUB",
                            "key_expr": key_expr,
                            "payload": msg_data,
                            "ts": time.time(),
                        }
                        self.bus_messages.append(bus_msg)
                        if len(self.bus_messages) > 500:
                            self.bus_messages = self.bus_messages[-500:]

                        # Broadcast to GUI clients
                        await self._broadcast_all(WSMessage(
                            type=MsgType.SENSOR_DATA,
                            source="hw_bus" if self.mode == "hw" else "engine",
                            payload=msg_data,
                        ))

                # 2. Flow checkpoints
                self.flow_checkpoints = ["CP_SENSOR", "CP_ACTUATOR", "CP_QUERY", "CP_DIAG"]

                # 3. Check watchdog
                self.check_watchdog()

                # 4. Kick watchdog (auto)
                self.kick_watchdog()

                # 5. Push safety state
                if self._master_mgr:
                    await self._master_mgr.broadcast(WSMessage(
                        type=MsgType.SAFETY_STATE,
                        source="engine",
                        payload={
                            "state": self.safety_state.value,
                            "watchdog_remaining": round(
                                max(0, self.watchdog_timeout - (time.time() - self.watchdog_last_kick)), 1
                            ),
                            "flow": self.flow_checkpoints,
                            "dtc_count": len(self.dtc_active),
                        },
                    ))

                # 6. Push PLCA status
                if self._master_mgr and cycle % 5 == 0:
                    await self._master_mgr.broadcast(WSMessage(
                        type=MsgType.PLCA_STATUS,
                        source="engine",
                        payload={
                            "beacon_active": self.plca_beacon_active,
                            "node_count": self.plca_node_count,
                            "collisions": self.plca_collisions,
                        },
                    ))

                # 7. Push node statuses
                if cycle % 3 == 0:
                    for nid, n in self.nodes.items():
                        status_payload = {
                            "node_id": nid,
                            "alive": n.alive,
                            "plca_id": n.plca_id,
                            "zone": n.zone,
                            "role": n.role,
                            "tx_count": n.tx_count,
                            "rx_count": n.rx_count,
                            "error_count": n.error_count,
                            "uptime": round(n.uptime, 1),
                            "sensors": n.sensors,
                            "actuators": n.actuators,
                            "e2e_ok": n.e2e_ok,
                            "e2e_fail": n.e2e_fail,
                            "secoc_ok": n.secoc_ok,
                            "secoc_fail": n.secoc_fail,
                            "seq_counter": n.seq_counter,
                        }
                        await self._broadcast_all(WSMessage(
                            type=MsgType.NODE_STATUS,
                            source="engine",
                            payload=status_payload,
                        ))

                await asyncio.sleep(1.0)  # 1Hz cycle
        finally:
            if self.mode == "hw":
                self._stop_ns_slave_nodes()
                self._close_zenoh()

    def stop(self) -> None:
        self.running = False


# Singleton
_engine: SimEngine | None = None


def get_engine(mode: str = "sim") -> SimEngine:
    global _engine
    if _engine is None:
        _engine = SimEngine(mode=mode)
    return _engine
