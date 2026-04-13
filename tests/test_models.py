"""Tests for data models (PRD Section 5.2)."""

from src.common.models import (
    SensorData,
    SensorType,
    ActuatorCommand,
    ActuatorType,
    NodeStatus,
    NodeInfo,
    NodeRole,
    PLCAConfig,
)


class TestSensorData:
    def test_create_and_serialize(self):
        data = SensorData(value=25.3, unit="celsius", ts=1713000000000)
        d = data.to_dict()
        assert d["value"] == 25.3
        assert d["unit"] == "celsius"
        assert d["ts"] == 1713000000000

    def test_from_dict(self):
        d = {"value": 101.3, "unit": "kpa", "ts": 1713000000000}
        data = SensorData.from_dict(d)
        assert data.value == 101.3
        assert data.unit == "kpa"

    def test_auto_timestamp(self):
        data = SensorData(value=0, unit="test")
        assert data.ts > 0


class TestActuatorCommand:
    def test_create_and_serialize(self):
        cmd = ActuatorCommand(
            action="set",
            params={"state": "on", "brightness": 80},
            ts=100,
        )
        d = cmd.to_dict()
        assert d["action"] == "set"
        assert d["params"]["brightness"] == 80

    def test_from_dict(self):
        d = {"action": "unlock", "params": {}, "ts": 200}
        cmd = ActuatorCommand.from_dict(d)
        assert cmd.action == "unlock"


class TestNodeStatus:
    def test_roundtrip(self):
        status = NodeStatus(
            alive=True,
            uptime_sec=3600,
            firmware_version="1.0.0",
            error_count=0,
            plca_node_id=1,
            tx_count=15000,
            rx_count=14980,
        )
        d = status.to_dict()
        restored = NodeStatus.from_dict(d)
        assert restored.alive is True
        assert restored.plca_node_id == 1
        assert restored.tx_count == 15000


class TestPLCAConfig:
    def test_coordinator(self):
        config = PLCAConfig(node_id=0)
        assert config.is_coordinator is True

    def test_follower(self):
        config = PLCAConfig(node_id=3)
        assert config.is_coordinator is False

    def test_worst_case_cycle(self):
        config = PLCAConfig(node_count=8)
        # 8 nodes * 1518B * 8bits + 20 beacon = 97172 bits
        # 97172 / 10M * 1000 = ~9.72ms
        assert 9.5 < config.worst_case_cycle_ms < 10.0

    def test_min_cycle(self):
        config = PLCAConfig(node_count=8, to_timer=0x20)
        # (20 + 8*32) / 10M * 1M = 27.6 µs
        assert 27.0 < config.min_cycle_us < 28.0

    def test_defaults(self):
        config = PLCAConfig()
        assert config.interface == "eth1"
        assert config.enabled is True
        assert config.node_count == 8
        assert config.to_timer == 0x20


class TestEnums:
    def test_sensor_types(self):
        assert SensorType.TEMPERATURE.value == "temperature"
        assert SensorType.BATTERY.value == "battery"

    def test_actuator_types(self):
        assert ActuatorType.LED.value == "led"
        assert ActuatorType.LOCK.value == "lock"

    def test_node_roles(self):
        assert NodeRole.SENSOR.value == "sensor"
        assert NodeRole.MIXED.value == "mixed"
