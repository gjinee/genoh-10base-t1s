"""Bypass integration tests — full Zenoh protocol over TCP loopback.

Tests the real Zenoh pub/sub/query/liveliness stack WITHOUT:
- 10BASE-T1S hardware (EVB-LAN8670-USB)
- ethtool / PLCA configuration
- zenohd router binary (uses peer mode instead)

Uses zenoh Python API in peer mode on localhost to verify:
1. Session open/close
2. Pub/Sub message flow (sensor data)
3. Query/Reply (node status)
4. Liveliness tokens (online/offline detection)
5. Full scenario sequence execution
"""

from __future__ import annotations

import json
import threading
import time

import pytest
import zenoh

from src.common import key_expressions as ke
from src.common import payloads
from src.common.models import ActuatorCommand, NodeStatus, PLCAConfig, SensorData
from src.master.network_setup import NetworkSetup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _peer_config() -> zenoh.Config:
    """Create a Zenoh config in peer mode (no router needed)."""
    conf = zenoh.Config()
    conf.insert_json5("mode", '"peer"')
    conf.insert_json5("listen/endpoints", '["tcp/127.0.0.1:0"]')
    conf.insert_json5("scouting/multicast/enabled", "false")
    return conf


def _client_config(endpoint: str) -> zenoh.Config:
    """Create a Zenoh config in client mode connecting to a specific endpoint."""
    conf = zenoh.Config()
    conf.insert_json5("mode", '"client"')
    conf.insert_json5("connect/endpoints", json.dumps([endpoint]))
    return conf


# ---------------------------------------------------------------------------
# Test 1: Zenoh Session Lifecycle
# ---------------------------------------------------------------------------

class TestZenohSession:
    """Verify Zenoh session can open and close on loopback."""

    def test_peer_session_open_close(self):
        zenoh.init_log_from_env_or("error")
        conf = _peer_config()
        session = zenoh.open(conf)
        zid = str(session.zid())
        assert len(zid) > 0
        session.close()

    def test_two_peers_connect(self):
        """Two peer sessions can see each other via TCP loopback."""
        zenoh.init_log_from_env_or("error")

        # Peer 1 listens
        conf1 = zenoh.Config()
        conf1.insert_json5("mode", '"peer"')
        conf1.insert_json5("listen/endpoints", '["tcp/127.0.0.1:17447"]')
        conf1.insert_json5("scouting/multicast/enabled", "false")
        session1 = zenoh.open(conf1)

        # Peer 2 connects
        conf2 = zenoh.Config()
        conf2.insert_json5("mode", '"client"')
        conf2.insert_json5("connect/endpoints", '["tcp/127.0.0.1:17447"]')
        session2 = zenoh.open(conf2)

        time.sleep(0.5)

        assert str(session1.zid()) != str(session2.zid())

        session2.close()
        session1.close()


# ---------------------------------------------------------------------------
# Test 2: Pub/Sub — Sensor Data Flow (PRD FR-003)
# ---------------------------------------------------------------------------

class TestPubSub:
    """Test real Zenoh publish/subscribe for sensor data."""

    def test_sensor_data_pubsub(self):
        """Master subscribes → Slave publishes → Master receives sensor data."""
        zenoh.init_log_from_env_or("error")

        conf1 = zenoh.Config()
        conf1.insert_json5("mode", '"peer"')
        conf1.insert_json5("listen/endpoints", '["tcp/127.0.0.1:17448"]')
        conf1.insert_json5("scouting/multicast/enabled", "false")
        master = zenoh.open(conf1)

        conf2 = _client_config("tcp/127.0.0.1:17448")
        slave = zenoh.open(conf2)
        time.sleep(0.3)

        received = []
        key = ke.sensor_key("front_left", 1, "temperature")

        # Master subscribes
        def on_sample(sample: zenoh.Sample):
            data = payloads.decode(sample.payload.to_bytes())
            received.append(data)

        master.declare_subscriber(key, on_sample)
        time.sleep(0.2)

        # Slave publishes sensor data
        sensor = SensorData(value=25.3, unit="celsius")
        slave.put(key, payloads.encode(sensor.to_dict()))
        time.sleep(0.5)

        assert len(received) == 1
        assert received[0]["value"] == 25.3
        assert received[0]["unit"] == "celsius"

        slave.close()
        master.close()

    def test_wildcard_subscription(self):
        """Master subscribes to vehicle/*/sensor/* and receives from multiple nodes."""
        zenoh.init_log_from_env_or("error")

        conf1 = zenoh.Config()
        conf1.insert_json5("mode", '"peer"')
        conf1.insert_json5("listen/endpoints", '["tcp/127.0.0.1:17449"]')
        conf1.insert_json5("scouting/multicast/enabled", "false")
        master = zenoh.open(conf1)

        conf2 = _client_config("tcp/127.0.0.1:17449")
        slave = zenoh.open(conf2)
        time.sleep(0.3)

        received = []
        pattern = ke.all_sensors_pattern()  # vehicle/*/*/sensor/*

        def on_sample(sample: zenoh.Sample):
            received.append(str(sample.key_expr))

        master.declare_subscriber(pattern, on_sample)
        time.sleep(0.2)

        # Publish from different "nodes"
        slave.put(ke.sensor_key("front_left", 1, "temperature"), b'{"value":25}')
        slave.put(ke.sensor_key("rear_right", 2, "pressure"), b'{"value":101}')
        slave.put(ke.sensor_key("front", 3, "light"), b'{"value":500}')
        time.sleep(0.5)

        assert len(received) == 3
        assert "vehicle/front_left/1/sensor/temperature" in received
        assert "vehicle/rear_right/2/sensor/pressure" in received

        slave.close()
        master.close()


# ---------------------------------------------------------------------------
# Test 3: Actuator Command (PRD FR-004)
# ---------------------------------------------------------------------------

class TestActuatorCommand:
    """Test master → slave actuator command flow."""

    def test_actuator_pubsub(self):
        """Master publishes actuator command → Slave receives it."""
        zenoh.init_log_from_env_or("error")

        conf1 = zenoh.Config()
        conf1.insert_json5("mode", '"peer"')
        conf1.insert_json5("listen/endpoints", '["tcp/127.0.0.1:17450"]')
        conf1.insert_json5("scouting/multicast/enabled", "false")
        master = zenoh.open(conf1)

        conf2 = _client_config("tcp/127.0.0.1:17450")
        slave = zenoh.open(conf2)
        time.sleep(0.3)

        received_cmds = []
        key = ke.actuator_key("front_left", 2, "lock")

        # Slave subscribes to actuator commands
        def on_cmd(sample: zenoh.Sample):
            cmd = payloads.decode(sample.payload.to_bytes())
            received_cmds.append(cmd)

        slave.declare_subscriber(key, on_cmd)
        time.sleep(0.2)

        # Master publishes unlock command
        cmd = ActuatorCommand(action="unlock", params={"force": True})
        master.put(key, payloads.encode(cmd.to_dict()))
        time.sleep(0.5)

        assert len(received_cmds) == 1
        assert received_cmds[0]["action"] == "unlock"

        slave.close()
        master.close()


# ---------------------------------------------------------------------------
# Test 4: Query/Reply — Node Status (PRD FR-005)
# ---------------------------------------------------------------------------

class TestQueryReply:
    """Test Zenoh queryable for node status queries."""

    def test_status_query(self):
        """Master queries → Slave responds with node status."""
        zenoh.init_log_from_env_or("error")

        conf1 = zenoh.Config()
        conf1.insert_json5("mode", '"peer"')
        conf1.insert_json5("listen/endpoints", '["tcp/127.0.0.1:17451"]')
        conf1.insert_json5("scouting/multicast/enabled", "false")
        master = zenoh.open(conf1)

        conf2 = _client_config("tcp/127.0.0.1:17451")
        slave = zenoh.open(conf2)
        time.sleep(0.3)

        status_key = ke.status_key("front_left", 1)

        # Slave declares queryable
        status = NodeStatus(
            alive=True, uptime_sec=3600, firmware_version="1.0.0",
            error_count=0, plca_node_id=1, tx_count=100, rx_count=99,
        )

        def handle_query(query):
            query.reply(status_key, payloads.encode(status.to_dict()))

        queryable = slave.declare_queryable(status_key)

        # Run queryable handler in a thread
        def serve():
            try:
                with queryable.recv() as query:
                    handle_query(query)
            except Exception:
                pass

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        time.sleep(0.3)

        # Master queries
        replies = master.get(status_key, timeout=3.0)
        result = None
        for reply in replies:
            try:
                result = payloads.decode(reply.ok.payload.to_bytes())
            except Exception:
                pass

        assert result is not None
        assert result["alive"] is True
        assert result["plca_node_id"] == 1
        assert result["firmware_version"] == "1.0.0"

        slave.close()
        master.close()


# ---------------------------------------------------------------------------
# Test 5: Liveliness — Node Online/Offline (PRD FR-006)
# ---------------------------------------------------------------------------

class TestLiveliness:
    """Test Zenoh liveliness tokens for node presence detection."""

    def test_liveliness_online(self):
        """Slave declares liveliness token → Master detects node online."""
        zenoh.init_log_from_env_or("error")

        conf1 = zenoh.Config()
        conf1.insert_json5("mode", '"peer"')
        conf1.insert_json5("listen/endpoints", '["tcp/127.0.0.1:17452"]')
        conf1.insert_json5("scouting/multicast/enabled", "false")
        master = zenoh.open(conf1)

        conf2 = _client_config("tcp/127.0.0.1:17452")
        slave = zenoh.open(conf2)
        time.sleep(0.3)

        events = []

        def on_liveliness(sample: zenoh.Sample):
            events.append({
                "kind": str(sample.kind),
                "key": str(sample.key_expr),
            })

        # Master subscribes to liveliness
        pattern = ke.all_alive_pattern()  # vehicle/*/*/alive
        master.liveliness().declare_subscriber(pattern, on_liveliness)
        time.sleep(0.3)

        # Slave declares liveliness token
        alive = ke.alive_key("front_left", 1)
        token = slave.liveliness().declare_token(alive)
        time.sleep(0.5)

        assert len(events) >= 1
        assert "front_left" in events[0]["key"]

        # Cleanup
        token.undeclare()
        slave.close()
        master.close()

    def test_liveliness_offline(self):
        """Slave session closes → Master detects node offline (DELETE event)."""
        zenoh.init_log_from_env_or("error")

        conf1 = zenoh.Config()
        conf1.insert_json5("mode", '"peer"')
        conf1.insert_json5("listen/endpoints", '["tcp/127.0.0.1:17453"]')
        conf1.insert_json5("scouting/multicast/enabled", "false")
        master = zenoh.open(conf1)

        conf2 = _client_config("tcp/127.0.0.1:17453")
        slave = zenoh.open(conf2)
        time.sleep(0.3)

        events = []

        def on_liveliness(sample: zenoh.Sample):
            events.append({
                "kind": sample.kind,
                "key": str(sample.key_expr),
            })

        master.liveliness().declare_subscriber(
            ke.all_alive_pattern(), on_liveliness
        )
        time.sleep(0.2)

        # Slave goes online
        alive = ke.alive_key("front_left", 1)
        token = slave.liveliness().declare_token(alive)
        time.sleep(0.5)

        # Slave goes offline (session close = token auto-undeclare)
        slave.close()
        time.sleep(1.0)

        # Should have PUT (online) and DELETE (offline) events
        kinds = [e["kind"] for e in events]
        assert zenoh.SampleKind.PUT in kinds, f"Expected PUT in {kinds}"
        assert zenoh.SampleKind.DELETE in kinds, f"Expected DELETE in {kinds}"

        master.close()


# ---------------------------------------------------------------------------
# Test 6: CBOR over Zenoh (PRD Section 5.2 bandwidth optimization)
# ---------------------------------------------------------------------------

class TestCBOROverZenoh:
    """Test CBOR-encoded payloads over real Zenoh transport."""

    def test_cbor_sensor_roundtrip(self):
        """Slave sends CBOR → Master decodes correctly."""
        zenoh.init_log_from_env_or("error")

        conf1 = zenoh.Config()
        conf1.insert_json5("mode", '"peer"')
        conf1.insert_json5("listen/endpoints", '["tcp/127.0.0.1:17454"]')
        conf1.insert_json5("scouting/multicast/enabled", "false")
        master = zenoh.open(conf1)

        conf2 = _client_config("tcp/127.0.0.1:17454")
        slave = zenoh.open(conf2)
        time.sleep(0.3)

        received = []
        key = ke.sensor_key("front_left", 1, "temperature")

        def on_sample(sample: zenoh.Sample):
            raw = sample.payload.to_bytes()
            data = payloads.decode(raw)  # Auto-detect CBOR
            received.append(data)

        master.declare_subscriber(key, on_sample)
        time.sleep(0.2)

        # Slave sends CBOR-encoded data
        sensor = SensorData(value=36.7, unit="celsius")
        cbor_bytes = payloads.encode(sensor.to_dict(), payloads.ENCODING_CBOR)
        slave.put(key, cbor_bytes)
        time.sleep(0.5)

        assert len(received) == 1
        assert received[0]["value"] == 36.7
        assert received[0]["unit"] == "celsius"

        slave.close()
        master.close()


# ---------------------------------------------------------------------------
# Test 7: Network Setup Bypass (mock ethtool)
# ---------------------------------------------------------------------------

class TestNetworkSetupBypass:
    """Test NetworkSetup with non-existent interface (graceful failure)."""

    @pytest.mark.asyncio
    async def test_initialize_no_hardware(self):
        """Full init sequence should fail gracefully without hardware."""
        config = PLCAConfig(interface="lo")  # loopback exists but isn't 10BASE-T1S
        ns = NetworkSetup(config)
        # Should not crash — just return True/False
        result = await ns.detect_interface()
        # loopback exists, so detect returns True
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_plca_config_no_hardware(self):
        """PLCA configure should fail gracefully without real hardware."""
        config = PLCAConfig(interface="lo")
        ns = NetworkSetup(config)
        result = await ns.configure_plca()
        # ethtool --set-plca-cfg on loopback will fail
        assert result is False


# ---------------------------------------------------------------------------
# Test 8: Multi-Node Scenario Simulation
# ---------------------------------------------------------------------------

class TestMultiNodeScenario:
    """Simulate a mini door-zone scenario over loopback."""

    def test_door_zone_mini(self):
        """
        Simulates PRD Scenario A (door zone) over loopback:
        1. Sensor node publishes proximity < 30
        2. Master detects condition
        3. Master sends unlock command
        4. Actuator node receives command
        """
        zenoh.init_log_from_env_or("error")

        # Setup: master (peer) + slave (client)
        conf1 = zenoh.Config()
        conf1.insert_json5("mode", '"peer"')
        conf1.insert_json5("listen/endpoints", '["tcp/127.0.0.1:17455"]')
        conf1.insert_json5("scouting/multicast/enabled", "false")
        master = zenoh.open(conf1)

        conf2 = _client_config("tcp/127.0.0.1:17455")
        slave = zenoh.open(conf2)
        time.sleep(0.3)

        # Keys
        proximity_key = ke.sensor_key("front_left", 1, "proximity")
        lock_key = ke.actuator_key("front_left", 2, "lock")

        # Track state
        sensor_values = []
        actuator_cmds = []

        # Master subscribes to proximity sensor
        def on_proximity(sample: zenoh.Sample):
            data = payloads.decode(sample.payload.to_bytes())
            sensor_values.append(data["value"])
            # If proximity < 30, send unlock
            if data["value"] < 30:
                cmd = ActuatorCommand(action="unlock")
                master.put(lock_key, payloads.encode(cmd.to_dict()))

        master.declare_subscriber(proximity_key, on_proximity)

        # Slave (actuator) subscribes to lock commands
        def on_lock_cmd(sample: zenoh.Sample):
            cmd = payloads.decode(sample.payload.to_bytes())
            actuator_cmds.append(cmd)

        slave.declare_subscriber(lock_key, on_lock_cmd)
        time.sleep(0.3)

        # Slave (sensor) publishes proximity = 20cm (< 30 threshold)
        sensor = SensorData(value=20.0, unit="cm")
        slave.put(proximity_key, payloads.encode(sensor.to_dict()))
        time.sleep(1.0)

        # Verify: sensor received, unlock command sent and received
        assert len(sensor_values) >= 1
        assert sensor_values[0] == 20.0
        assert len(actuator_cmds) >= 1
        assert actuator_cmds[0]["action"] == "unlock"

        slave.close()
        master.close()
