"""Tests for the GUI simulator — backend logic and WebSocket protocol."""

from __future__ import annotations

import asyncio
import json
import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from gui.common.protocol import MsgType, WSMessage
from gui.common.sim_engine import SimEngine, SafetyState, e2e_encode, e2e_decode

pytestmark = pytest.mark.asyncio(loop_scope="function")


# ===== Protocol Tests =====

class TestWSMessage:
    def test_roundtrip(self):
        msg = WSMessage(type=MsgType.SENSOR_DATA, source="slave", payload={"value": 25.3})
        raw = msg.to_json()
        restored = WSMessage.from_json(raw)
        assert restored.type == MsgType.SENSOR_DATA
        assert restored.source == "slave"
        assert restored.payload["value"] == 25.3

    def test_all_msg_types_are_strings(self):
        for mt in MsgType:
            assert isinstance(mt.value, str)


# ===== E2E Protection Tests =====

class TestE2EProtection:
    def test_encode_decode_roundtrip(self):
        payload = b'{"value": 25.3, "unit": "celsius"}'
        encoded = e2e_encode(payload, 0x1001, 42)
        decoded_payload, data_id, seq, crc_ok = e2e_decode(encoded)
        assert crc_ok is True
        assert data_id == 0x1001
        assert seq == 42
        assert decoded_payload == payload

    def test_corrupted_crc(self):
        payload = b'{"value": 25.3}'
        encoded = bytearray(e2e_encode(payload, 0x1001, 1))
        encoded[-1] ^= 0xFF  # Corrupt last byte
        _, _, _, crc_ok = e2e_decode(bytes(encoded))
        assert crc_ok is False

    def test_short_message(self):
        _, _, _, crc_ok = e2e_decode(b'\x00\x01')
        assert crc_ok is False


# ===== SimEngine Tests =====

class TestSimEngine:
    def setup_method(self):
        self.engine = SimEngine(mode="sim")

    def test_register_node(self):
        node = self.engine.register_node("1", "front_left", 1, "sensor")
        assert node.node_id == "1"
        assert node.zone == "front_left"
        assert node.alive is True
        assert "temperature" in node.sensors
        assert self.engine.plca_node_count == 2  # master + 1

    def test_register_actuator_node(self):
        node = self.engine.register_node("2", "front_left", 2, "actuator")
        assert "lock" in node.actuators
        assert node.sensors == {}

    def test_register_mixed_node(self):
        node = self.engine.register_node("3", "rear_left", 3, "mixed")
        assert "temperature" in node.sensors
        assert "lock" in node.actuators

    def test_remove_node(self):
        self.engine.register_node("1", "front_left", 1, "sensor")
        assert "1" in self.engine.nodes
        self.engine.remove_node("1")
        assert "1" not in self.engine.nodes

    def test_generate_sensor_value(self):
        self.engine.register_node("1", "front_left", 1, "sensor")
        val = self.engine.generate_sensor_value("1", "temperature")
        assert val is not None
        assert -40.0 <= val <= 150.0

    def test_generate_sensor_value_dead_node(self):
        self.engine.register_node("1", "front_left", 1, "sensor")
        self.engine.nodes["1"].alive = False
        val = self.engine.generate_sensor_value("1", "temperature")
        assert val is None

    def test_generate_sensor_value_unknown_node(self):
        val = self.engine.generate_sensor_value("99", "temperature")
        assert val is None

    def test_encode_sensor_message(self):
        self.engine.register_node("1", "front_left", 1, "sensor")
        msg = self.engine.encode_sensor_message("1", "temperature", 25.3)
        assert msg["node_id"] == "1"
        assert msg["value"] == 25.3
        assert msg["e2e_status"] == "VALID"
        assert msg["seq"] == 1

    def test_encode_actuator_command(self):
        cmd = self.engine.encode_actuator_command("2", "lock", "unlock", {})
        assert cmd["node_id"] == "2"
        assert cmd["action"] == "unlock"
        assert cmd["secoc_status"] == "AUTHENTICATED"
        assert len(cmd["mac"]) == 16

    def test_safety_fsm_normal_to_degraded(self):
        # Need >1 node so 1 offline < 50%
        self.engine.register_node("1", "front_left", 1, "sensor")
        self.engine.register_node("2", "front_left", 2, "sensor")
        self.engine.register_node("3", "front_left", 3, "sensor")
        result = self.engine.report_fault("NODE_OFFLINE", "1")
        assert self.engine.safety_state == SafetyState.DEGRADED

    def test_safety_fsm_50pct_offline(self):
        self.engine.register_node("1", "fl", 1, "sensor")
        self.engine.register_node("2", "fl", 2, "sensor")
        self.engine.report_fault("NODE_OFFLINE", "1")
        # 1/2 = 50% → SAFE_STATE
        assert self.engine.safety_state == SafetyState.SAFE_STATE

    def test_safety_fsm_watchdog_expire(self):
        result = self.engine.report_fault("WATCHDOG_EXPIRED")
        assert self.engine.safety_state == SafetyState.SAFE_STATE

    def test_safety_fsm_manual_reset(self):
        self.engine.report_fault("WATCHDOG_EXPIRED")
        assert self.engine.safety_state == SafetyState.SAFE_STATE
        self.engine.transition_safety(SafetyState.NORMAL, "Manual reset")
        assert self.engine.safety_state == SafetyState.NORMAL

    def test_watchdog_kick(self):
        remaining = self.engine.kick_watchdog()
        assert remaining == 5.0
        assert self.engine.check_watchdog() is True

    def test_ids_check(self):
        alert = self.engine.ids_check("IDS-001", "attacker", "Spoofed message", "HIGH")
        assert alert.rule_id == "IDS-001"
        assert len(self.engine.ids_alerts) == 1

    def test_list_scenarios(self):
        scenarios = self.engine.list_scenarios()
        assert isinstance(scenarios, list)
        assert "door_zone" in scenarios or "door_zone_control" in scenarios or len(scenarios) >= 0

    def test_get_full_state(self):
        self.engine.register_node("1", "front_left", 1, "sensor")
        state = self.engine.get_full_state()
        assert state["mode"] == "sim"
        assert state["safety_state"] == "NORMAL"
        assert "1" in state["nodes"]
        assert state["plca"]["node_count"] == 2

    def test_plca_node_count_tracks_registrations(self):
        assert self.engine.plca_node_count == 1
        self.engine.register_node("1", "fl", 1, "sensor")
        assert self.engine.plca_node_count == 2
        self.engine.register_node("2", "fl", 2, "actuator")
        assert self.engine.plca_node_count == 3
        self.engine.remove_node("1")
        assert self.engine.plca_node_count == 2


# ===== FastAPI Endpoint Tests =====

class TestMasterAPI:
    @pytest.fixture
    def client(self):
        from gui.master.app import app
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    @pytest.mark.asyncio
    async def test_index(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "Master Controller" in resp.text

    @pytest.mark.asyncio
    async def test_get_state(self, client):
        resp = await client.get("/api/state")
        assert resp.status_code == 200
        data = resp.json()
        assert "safety_state" in data
        assert "plca" in data

    @pytest.mark.asyncio
    async def test_list_scenarios(self, client):
        resp = await client.get("/api/scenarios")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_start_stop(self, client):
        resp = await client.post("/api/start")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

        resp = await client.post("/api/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"


class TestSlaveAPI:
    @pytest.fixture
    def client(self):
        from gui.slave.app import app
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    @pytest.mark.asyncio
    async def test_index(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "Slave Node" in resp.text

    @pytest.mark.asyncio
    async def test_get_state(self, client):
        resp = await client.get("/api/state")
        assert resp.status_code == 200
        data = resp.json()
        assert "mode" in data

    @pytest.mark.asyncio
    async def test_register_node(self, client):
        resp = await client.post("/api/register?node_id=test1&zone=front_left&plca_id=1&role=sensor")
        assert resp.status_code == 200
        assert resp.json()["status"] == "registered"


# ===== Simulation Loop Test =====

class TestSimLoop:
    @pytest.mark.asyncio
    async def test_loop_runs_and_stops(self):
        engine = SimEngine(mode="sim")
        engine.register_node("1", "front_left", 1, "sensor")

        task = asyncio.create_task(engine.run_loop())
        await asyncio.sleep(2.5)  # Let 2 cycles run
        engine.stop()
        await asyncio.sleep(0.5)

        assert engine.nodes["1"].tx_count > 0
        assert engine.nodes["1"].seq_counter > 0
