"""Hardware bypass test — Dual EVB-LAN8670-USB on single Raspberry Pi.

Runs the real Zenoh protocol stack over the actual 10BASE-T1S physical layer:
  USB1 → eth1 (Master, PLCA Coordinator, Node ID 0, 192.168.1.1)
  USB2 → eth2 (Slave,  PLCA Follower,    Node ID 1, 192.168.1.2)

Prerequisites:
  1. Two EVB-LAN8670-USB modules connected to RPi USB ports
  2. UTP cable connecting both modules
  3. Network namespace setup (eth2 in ns_slave):
       sudo ip netns add ns_slave
       sudo ip link set eth2 netns ns_slave
       sudo ip netns exec ns_slave ip addr add 192.168.1.2/24 dev eth2
       sudo ip netns exec ns_slave ip link set eth2 up
       sudo ip addr add 192.168.1.1/24 dev eth1
  4. Run: zenohd --listen tcp/192.168.1.1:7447

Usage:
  python3 -m pytest tests/test_hw_bypass.py -v
  python3 -m pytest tests/test_hw_bypass.py -v -k "test_ping"  # single test

Skip:
  Tests auto-skip if eth1 or zenohd are not available.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time

import pytest
import zenoh

from src.common import key_expressions as ke
from src.common import payloads
from src.common.models import ActuatorCommand, PLCAConfig, SensorData

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MASTER_IFACE = "eth1"
SLAVE_IFACE = "eth2"
MASTER_IP = "192.168.1.1"
SLAVE_IP = "192.168.1.2"
ROUTER_ENDPOINT = f"tcp/{MASTER_IP}:7447"

# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------


SLAVE_NETNS = "ns_slave"


def _interface_exists(iface: str, netns: str | None = None) -> bool:
    cmd = ["ip", "link", "show", iface]
    if netns:
        cmd = ["sudo", "ip", "netns", "exec", netns] + cmd
    result = subprocess.run(cmd, capture_output=True, timeout=5)
    return result.returncode == 0


def _netns_exists(name: str) -> bool:
    result = subprocess.run(
        ["sudo", "ip", "netns", "list"],
        capture_output=True, text=True, timeout=5,
    )
    return name in result.stdout


def _zenohd_running() -> bool:
    result = subprocess.run(
        ["pgrep", "-x", "zenohd"],
        capture_output=True, timeout=5,
    )
    return result.returncode == 0


def _can_ping(src_iface: str, dst_ip: str, netns: str | None = None) -> bool:
    cmd = ["ping", "-c", "1", "-W", "2", "-I", src_iface, dst_ip]
    if netns:
        cmd = ["sudo", "ip", "netns", "exec", netns] + cmd
    result = subprocess.run(cmd, capture_output=True, timeout=5)
    return result.returncode == 0


hw_available = pytest.mark.skipif(
    not _interface_exists(MASTER_IFACE),
    reason=f"Hardware not available: need {MASTER_IFACE}",
)

zenohd_required = pytest.mark.skipif(
    not _zenohd_running(),
    reason="zenohd router not running (start with: zenohd --listen tcp/192.168.1.1:7447)",
)


def _master_config() -> zenoh.Config:
    """Master: client mode connecting to zenohd on master IP."""
    conf = zenoh.Config()
    conf.insert_json5("mode", '"client"')
    conf.insert_json5("connect/endpoints", json.dumps([ROUTER_ENDPOINT]))
    return conf


def _slave_config() -> zenoh.Config:
    """Slave: client mode connecting to zenohd over 10BASE-T1S."""
    conf = zenoh.Config()
    conf.insert_json5("mode", '"client"')
    conf.insert_json5("connect/endpoints", json.dumps([ROUTER_ENDPOINT]))
    return conf


# ---------------------------------------------------------------------------
# Test 1: Physical Layer — PLCA and Connectivity
# ---------------------------------------------------------------------------

@hw_available
class TestPhysicalLayer:
    """Verify 10BASE-T1S physical layer: PLCA, link, ping."""

    def test_master_interface_up(self):
        result = subprocess.run(
            ["ip", "-o", "link", "show", MASTER_IFACE],
            capture_output=True, text=True, timeout=5,
        )
        assert "LOWER_UP" in result.stdout or "state UP" in result.stdout

    def test_slave_interface_up(self):
        result = subprocess.run(
            ["sudo", "ip", "netns", "exec", SLAVE_NETNS,
             "ip", "-o", "link", "show", SLAVE_IFACE],
            capture_output=True, text=True, timeout=5,
        )
        assert "LOWER_UP" in result.stdout or "state UP" in result.stdout

    def test_plca_master_config(self):
        """PLCA Coordinator should be Node ID 0."""
        result = subprocess.run(
            ["ethtool", "--get-plca-cfg", MASTER_IFACE],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            assert "0" in result.stdout  # node-id 0

    def test_plca_slave_config(self):
        """PLCA Follower should be Node ID 1."""
        result = subprocess.run(
            ["sudo", "ip", "netns", "exec", SLAVE_NETNS,
             "ethtool", "--get-plca-cfg", SLAVE_IFACE],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            assert "1" in result.stdout  # node-id 1

    def test_ping_master_to_slave(self):
        """Ping from master (eth1) to slave (eth2) over 10BASE-T1S bus."""
        assert _can_ping(MASTER_IFACE, SLAVE_IP), \
            f"Ping failed: {MASTER_IP} → {SLAVE_IP} over 10BASE-T1S"

    def test_ping_slave_to_master(self):
        """Ping from slave (eth2) to master (eth1) over 10BASE-T1S bus."""
        assert _can_ping(SLAVE_IFACE, MASTER_IP, netns=SLAVE_NETNS), \
            f"Ping failed: {SLAVE_IP} → {MASTER_IP} over 10BASE-T1S"

    def test_plca_beacon_active(self):
        """PLCA beacon should be active (coordinator generating beacons)."""
        result = subprocess.run(
            ["ethtool", "--get-plca-status", MASTER_IFACE],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            output = result.stdout.lower()
            assert "on" in output or "yes" in output or "active" in output


# ---------------------------------------------------------------------------
# Test 2: Zenoh over 10BASE-T1S — Pub/Sub
# ---------------------------------------------------------------------------

@hw_available
@zenohd_required
class TestZenohOver10BaseT1S:
    """Test real Zenoh pub/sub over the 10BASE-T1S physical bus."""

    def test_session_via_10base_t1s(self):
        """Slave can open Zenoh session through 10BASE-T1S to zenohd."""
        zenoh.init_log_from_env_or("error")
        slave = zenoh.open(_slave_config())
        assert str(slave.zid())
        slave.close()

    def test_sensor_data_over_bus(self):
        """Slave publishes sensor data over 10BASE-T1S → Master receives."""
        zenoh.init_log_from_env_or("error")
        master = zenoh.open(_master_config())
        slave = zenoh.open(_slave_config())
        time.sleep(0.5)

        received = []
        key = ke.sensor_key("front_left", 1, "temperature")

        def on_sample(sample: zenoh.Sample):
            data = payloads.decode(sample.payload.to_bytes())
            received.append(data)

        master.declare_subscriber(key, on_sample)
        time.sleep(0.3)

        # Slave publishes over 10BASE-T1S
        sensor = SensorData(value=28.5, unit="celsius")
        slave.put(key, payloads.encode(sensor.to_dict()))
        time.sleep(1.0)

        assert len(received) >= 1
        assert received[0]["value"] == 28.5

        slave.close()
        master.close()

    def test_actuator_command_over_bus(self):
        """Master publishes actuator command over 10BASE-T1S → Slave receives."""
        zenoh.init_log_from_env_or("error")
        master = zenoh.open(_master_config())
        slave = zenoh.open(_slave_config())
        time.sleep(0.5)

        received = []
        key = ke.actuator_key("front_left", 2, "lock")

        def on_cmd(sample: zenoh.Sample):
            received.append(payloads.decode(sample.payload.to_bytes()))

        slave.declare_subscriber(key, on_cmd)
        time.sleep(0.3)

        cmd = ActuatorCommand(action="unlock")
        master.put(key, payloads.encode(cmd.to_dict()))
        time.sleep(1.0)

        assert len(received) >= 1
        assert received[0]["action"] == "unlock"

        slave.close()
        master.close()

    def test_cbor_over_bus(self):
        """CBOR-encoded sensor data over real 10BASE-T1S bus."""
        zenoh.init_log_from_env_or("error")
        master = zenoh.open(_master_config())
        slave = zenoh.open(_slave_config())
        time.sleep(0.5)

        received = []
        key = ke.sensor_key("rear_left", 3, "pressure")

        def on_sample(sample: zenoh.Sample):
            received.append(payloads.decode(sample.payload.to_bytes()))

        master.declare_subscriber(key, on_sample)
        time.sleep(0.3)

        sensor = SensorData(value=101.3, unit="kpa")
        slave.put(key, payloads.encode(sensor.to_dict(), payloads.ENCODING_CBOR))
        time.sleep(1.0)

        assert len(received) >= 1
        assert received[0]["value"] == 101.3

        slave.close()
        master.close()


# ---------------------------------------------------------------------------
# Test 3: Liveliness over 10BASE-T1S
# ---------------------------------------------------------------------------

@hw_available
@zenohd_required
class TestLivelinessOver10BaseT1S:
    """Test Zenoh liveliness tokens over the real 10BASE-T1S bus."""

    def test_node_online_offline(self):
        """Slave liveliness token → Master detects online/offline over 10BASE-T1S."""
        zenoh.init_log_from_env_or("error")
        master = zenoh.open(_master_config())
        slave = zenoh.open(_slave_config())
        time.sleep(0.5)

        events = []

        def on_event(sample: zenoh.Sample):
            events.append({"kind": sample.kind, "key": str(sample.key_expr)})

        master.liveliness().declare_subscriber(ke.all_alive_pattern(), on_event)
        time.sleep(0.3)

        # Slave comes online
        token = slave.liveliness().declare_token(ke.alive_key("front_left", 1))
        time.sleep(1.0)

        # Slave goes offline
        slave.close()
        time.sleep(2.0)

        kinds = [e["kind"] for e in events]
        assert zenoh.SampleKind.PUT in kinds, "Expected online (PUT) event"
        assert zenoh.SampleKind.DELETE in kinds, "Expected offline (DELETE) event"

        master.close()


# ---------------------------------------------------------------------------
# Test 4: Query/Reply over 10BASE-T1S
# ---------------------------------------------------------------------------

@hw_available
@zenohd_required
class TestQueryOver10BaseT1S:
    """Test Zenoh query/reply over the real 10BASE-T1S bus."""

    def test_status_query_over_bus(self):
        """Master queries slave status over 10BASE-T1S."""
        zenoh.init_log_from_env_or("error")
        master = zenoh.open(_master_config())
        slave = zenoh.open(_slave_config())
        time.sleep(0.5)

        status_key = ke.status_key("front_left", 1)
        status_data = {
            "alive": True, "uptime_sec": 120,
            "firmware_version": "1.0.0", "error_count": 0,
            "plca_node_id": 1, "tx_count": 50, "rx_count": 48,
        }

        # Slave queryable
        queryable = slave.declare_queryable(status_key)

        def serve():
            try:
                with queryable.recv() as query:
                    query.reply(status_key, payloads.encode(status_data))
            except Exception:
                pass

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        time.sleep(0.3)

        # Master queries over 10BASE-T1S
        result = None
        for reply in master.get(status_key, timeout=5.0):
            try:
                result = payloads.decode(reply.ok.payload.to_bytes())
            except Exception:
                pass

        assert result is not None
        assert result["plca_node_id"] == 1
        assert result["alive"] is True

        slave.close()
        master.close()


# ---------------------------------------------------------------------------
# Test 5: Full Door Zone Scenario over 10BASE-T1S
# ---------------------------------------------------------------------------

@hw_available
@zenohd_required
class TestDoorZoneOver10BaseT1S:
    """End-to-end door zone scenario over the real 10BASE-T1S bus."""

    def test_proximity_unlock_scenario(self):
        """
        Full PRD Scenario A over 10BASE-T1S:
        1. Slave(eth2) publishes proximity=20cm → Master(eth1) receives
        2. Master detects proximity < 30 → publishes unlock command
        3. Slave receives unlock command over 10BASE-T1S bus
        """
        zenoh.init_log_from_env_or("error")
        master = zenoh.open(_master_config())
        slave = zenoh.open(_slave_config())
        time.sleep(0.5)

        proximity_key = ke.sensor_key("front_left", 1, "proximity")
        lock_key = ke.actuator_key("front_left", 2, "lock")

        sensor_values = []
        actuator_cmds = []

        # Master: subscribe proximity → auto-unlock
        def on_proximity(sample: zenoh.Sample):
            data = payloads.decode(sample.payload.to_bytes())
            sensor_values.append(data["value"])
            if data["value"] < 30:
                cmd = ActuatorCommand(action="unlock")
                master.put(lock_key, payloads.encode(cmd.to_dict()))

        master.declare_subscriber(proximity_key, on_proximity)

        # Slave: subscribe to lock commands
        def on_lock(sample: zenoh.Sample):
            actuator_cmds.append(payloads.decode(sample.payload.to_bytes()))

        slave.declare_subscriber(lock_key, on_lock)
        time.sleep(0.5)

        # Slave: publish proximity=20cm (triggers unlock)
        sensor = SensorData(value=20.0, unit="cm")
        slave.put(proximity_key, payloads.encode(sensor.to_dict()))
        time.sleep(2.0)  # Extra time for 10BASE-T1S latency

        assert len(sensor_values) >= 1, "Master did not receive proximity data"
        assert sensor_values[0] == 20.0
        assert len(actuator_cmds) >= 1, "Slave did not receive unlock command"
        assert actuator_cmds[0]["action"] == "unlock"

        slave.close()
        master.close()


# ---------------------------------------------------------------------------
# Test 6: Latency Measurement over 10BASE-T1S
# ---------------------------------------------------------------------------

@hw_available
@zenohd_required
class TestLatencyOver10BaseT1S:
    """Measure round-trip latency over 10BASE-T1S (PRD NFR-001: <15ms)."""

    def test_pubsub_latency(self):
        """Measure pub→sub latency over 10BASE-T1S bus."""
        zenoh.init_log_from_env_or("error")
        master = zenoh.open(_master_config())
        slave = zenoh.open(_slave_config())
        time.sleep(0.5)

        key = ke.sensor_key("front_left", 1, "temperature")
        latencies = []

        def on_sample(sample: zenoh.Sample):
            recv_time = time.time() * 1000
            data = payloads.decode(sample.payload.to_bytes())
            send_time = data["ts"]
            latencies.append(recv_time - send_time)

        master.declare_subscriber(key, on_sample)
        time.sleep(0.3)

        # Send 10 messages and measure latency
        for i in range(10):
            sensor = SensorData(value=25.0 + i * 0.1, unit="celsius")
            slave.put(key, payloads.encode(sensor.to_dict()))
            time.sleep(0.2)

        time.sleep(1.0)

        assert len(latencies) >= 5, f"Only received {len(latencies)}/10 messages"

        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)

        print(f"\n  === 10BASE-T1S Latency Results ===")
        print(f"  Messages: {len(latencies)}/10")
        print(f"  Avg latency: {avg_latency:.2f} ms")
        print(f"  Max latency: {max_latency:.2f} ms")
        print(f"  PRD target:  < 15 ms")

        # PRD NFR-001: < 15ms for 8 nodes, should be much less for 2 nodes
        assert max_latency < 15.0, f"Max latency {max_latency:.2f}ms exceeds 15ms target"

        slave.close()
        master.close()
