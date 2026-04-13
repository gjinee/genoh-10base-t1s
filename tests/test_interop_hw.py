"""Cross-language interop test — Python (zenoh) ↔ C (zenoh-pico) over 10BASE-T1S.

Tests real interoperability between:
  - Master: Python eclipse-zenoh (this process, default namespace, eth1)
  - Slave:  C zenoh-pico binaries (ns_slave namespace, eth2)
  - Router: zenohd on tcp/192.168.1.1:7447

All traffic traverses the physical 10BASE-T1S bus (EVB-LAN8670-USB x2).

Prerequisites:
  1. Two EVB-LAN8670-USB modules with UTP cable
  2. Network namespace: eth2 in ns_slave (192.168.1.2/24)
  3. zenohd running: zenohd --listen tcp/192.168.1.1:7447
  4. Slave binaries built: slave_examples/build/{sensor_node,actuator_node}

Usage:
  python3 -m pytest tests/test_interop_hw.py -v -s
"""

from __future__ import annotations

import json
import os
import subprocess
import time

import pytest
import zenoh

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROUTER_ENDPOINT = "tcp/192.168.1.1:7447"
SLAVE_NETNS = "ns_slave"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENSOR_BIN = os.path.join(PROJECT_ROOT, "slave_examples", "build", "sensor_node")
ACTUATOR_BIN = os.path.join(PROJECT_ROOT, "slave_examples", "build", "actuator_node")

# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------


def _zenohd_running() -> bool:
    result = subprocess.run(["pgrep", "-x", "zenohd"], capture_output=True, timeout=5)
    return result.returncode == 0


def _netns_exists() -> bool:
    result = subprocess.run(
        ["sudo", "ip", "netns", "list"],
        capture_output=True, text=True, timeout=5,
    )
    return SLAVE_NETNS in result.stdout


def _binaries_exist() -> bool:
    return os.path.isfile(SENSOR_BIN) and os.path.isfile(ACTUATOR_BIN)


skip_unless_ready = pytest.mark.skipif(
    not (_zenohd_running() and _netns_exists() and _binaries_exist()),
    reason="Need: zenohd running, ns_slave namespace, built slave binaries",
)


def _master_session() -> zenoh.Session:
    conf = zenoh.Config()
    conf.insert_json5("mode", '"client"')
    conf.insert_json5("connect/endpoints", json.dumps([ROUTER_ENDPOINT]))
    return zenoh.open(conf)


def _run_in_ns(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    """Run a command inside ns_slave network namespace."""
    full_cmd = ["sudo", "ip", "netns", "exec", SLAVE_NETNS] + cmd
    return subprocess.run(
        full_cmd, capture_output=True, text=True, timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Test 1: Pub/Sub — C sensor_node publishes, Python subscribes
# ---------------------------------------------------------------------------


@skip_unless_ready
class TestPubSubInterop:
    """zenoh-pico C publisher → zenohd → Python subscriber."""

    def test_sensor_node_to_python_subscriber(self):
        """C sensor_node publishes temperature data, Python receives it."""
        zenoh.init_log_from_env_or("error")
        master = _master_session()
        time.sleep(0.3)

        received = []
        key = "vehicle/front_left/1/sensor/temperature"

        def on_sample(sample: zenoh.Sample):
            payload = sample.payload.to_bytes().decode("utf-8")
            received.append(json.loads(payload))

        sub = master.declare_subscriber(key, on_sample)
        time.sleep(0.5)

        # Run C sensor_node in ns_slave: publish 5 messages
        proc = _run_in_ns(
            [SENSOR_BIN, "-e", ROUTER_ENDPOINT, "-c", "5"],
            timeout=20,
        )

        # Wait for messages to propagate
        time.sleep(1.0)

        print(f"\n  sensor_node stdout:\n{proc.stdout[:500]}")
        print(f"  Messages received by Python: {len(received)}")
        for i, msg in enumerate(received):
            print(f"    [{i}] value={msg.get('value')}, unit={msg.get('unit')}")

        assert proc.returncode == 0, f"sensor_node failed: {proc.stderr}"
        assert len(received) >= 3, f"Expected >=3 messages, got {len(received)}"
        assert all("value" in m and "unit" in m for m in received)
        assert all(m["unit"] == "celsius" for m in received)

        sub.undeclare()
        master.close()

    def test_python_publisher_to_actuator_node(self):
        """Python publishes actuator command, C actuator_node receives it."""
        zenoh.init_log_from_env_or("error")
        master = _master_session()
        time.sleep(0.3)

        key = "vehicle/front_left/2/actuator/lock"

        # Start actuator_node in background (waits for 2 messages)
        full_cmd = [
            "sudo", "ip", "netns", "exec", SLAVE_NETNS,
            ACTUATOR_BIN, "-e", ROUTER_ENDPOINT, "-c", "2",
        ]
        proc = subprocess.Popen(
            full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

        # Wait for actuator_node to connect and subscribe
        time.sleep(3.0)

        # Python master publishes 2 commands
        cmd1 = json.dumps({"action": "unlock", "ts": int(time.time() * 1000)})
        cmd2 = json.dumps({"action": "lock", "ts": int(time.time() * 1000)})
        master.put(key, cmd1.encode())
        time.sleep(0.5)
        master.put(key, cmd2.encode())

        # Wait for actuator_node to receive and exit
        try:
            stdout, stderr = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()

        print(f"\n  actuator_node stdout:\n{stdout[:500]}")

        assert "UNLOCK" in stdout, "actuator_node did not execute UNLOCK"
        assert "LOCK" in stdout, "actuator_node did not execute LOCK"

        master.close()


# ---------------------------------------------------------------------------
# Test 2: Query/Reply — Python queries, C queryable responds
# ---------------------------------------------------------------------------


@skip_unless_ready
class TestQueryInterop:
    """Python get() → zenohd → zenoh-pico C queryable → reply."""

    def test_status_query_to_sensor_node(self):
        """Python queries C sensor_node's status queryable."""
        zenoh.init_log_from_env_or("error")
        master = _master_session()
        time.sleep(0.3)

        status_key = "vehicle/front_left/1/status"

        # Start sensor_node in background (it declares a queryable)
        full_cmd = [
            "sudo", "ip", "netns", "exec", SLAVE_NETNS,
            SENSOR_BIN, "-e", ROUTER_ENDPOINT, "-c", "100",
        ]
        proc = subprocess.Popen(
            full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

        # Wait for sensor_node to connect and declare queryable
        time.sleep(3.0)

        # Python master sends query
        replies = []
        for reply in master.get(status_key, timeout=5.0):
            try:
                payload = reply.ok.payload.to_bytes().decode("utf-8")
                replies.append(json.loads(payload))
            except Exception:
                pass

        proc.kill()
        proc.wait()

        print(f"\n  Query replies: {len(replies)}")
        for r in replies:
            print(f"    {r}")

        assert len(replies) >= 1, "No reply from sensor_node queryable"
        assert replies[0]["alive"] is True
        assert "firmware_version" in replies[0]

        master.close()


# ---------------------------------------------------------------------------
# Test 3: Liveliness — C node online/offline detection from Python
# ---------------------------------------------------------------------------


@skip_unless_ready
class TestLivelinessInterop:
    """Python detects C node liveliness token over 10BASE-T1S."""

    def test_c_node_liveliness_detection(self):
        """C sensor_node declares liveliness token → Python detects online/offline."""
        zenoh.init_log_from_env_or("error")
        master = _master_session()
        time.sleep(0.3)

        events = []
        alive_pattern = "vehicle/*/*/alive"

        def on_event(sample: zenoh.Sample):
            events.append({
                "kind": str(sample.kind),
                "key": str(sample.key_expr),
            })

        master.liveliness().declare_subscriber(alive_pattern, on_event)
        time.sleep(0.5)

        # Start sensor_node in background (infinite mode), then kill it
        # to trigger lease timeout → DELETE event
        full_cmd = [
            "sudo", "ip", "netns", "exec", SLAVE_NETNS,
            SENSOR_BIN, "-e", ROUTER_ENDPOINT,
        ]
        proc = subprocess.Popen(
            full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

        # Wait for online event
        time.sleep(3.0)

        # Kill the actual sensor_node process (sudo child)
        subprocess.run(["sudo", "pkill", "-9", "-f", "sensor_node"], timeout=5)
        proc.wait()

        # Wait for zenohd lease timeout (default 10s) + margin
        time.sleep(12.0)

        print(f"\n  Liveliness events: {len(events)}")
        for e in events:
            print(f"    kind={e['kind']}, key={e['key']}")

        kinds = [e["kind"] for e in events]
        assert any("PUT" in k for k in kinds), "No online (PUT) event detected"
        assert any("DELETE" in k for k in kinds), "No offline (DELETE) event detected"

        master.close()


# ---------------------------------------------------------------------------
# Test 4: Bidirectional — full scenario over physical bus
# ---------------------------------------------------------------------------


@skip_unless_ready
class TestBidirectionalInterop:
    """Full bidirectional: C publishes sensor → Python reacts → C receives command."""

    def test_sensor_trigger_actuator_crosslang(self):
        """
        Cross-language scenario over 10BASE-T1S:
        1. C sensor_node publishes temperature data
        2. Python master subscribes and detects high temp (>27)
        3. Python master publishes actuator command (alert)
        4. C actuator_node receives command
        """
        zenoh.init_log_from_env_or("error")
        master = _master_session()
        time.sleep(0.3)

        sensor_key = "vehicle/front_left/1/sensor/temperature"
        alert_key = "vehicle/front_left/2/actuator/buzzer"
        sensor_readings = []

        # Master: subscribe sensor, auto-trigger alert on high temp
        def on_sensor(sample: zenoh.Sample):
            payload = sample.payload.to_bytes().decode("utf-8")
            data = json.loads(payload)
            sensor_readings.append(data)
            if data.get("value", 0) > 27.0:
                alert = json.dumps({"action": "set", "value": "on",
                                    "ts": int(time.time() * 1000)})
                master.put(alert_key, alert.encode())

        master.declare_subscriber(sensor_key, on_sensor)
        time.sleep(0.3)

        # Start actuator_node in background (listen for 1 alert)
        act_cmd = [
            "sudo", "ip", "netns", "exec", SLAVE_NETNS,
            ACTUATOR_BIN, "-e", ROUTER_ENDPOINT,
            "-z", "front_left", "-n", "2", "-t", "buzzer", "-c", "1",
        ]
        act_proc = subprocess.Popen(
            act_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        time.sleep(2.0)

        # Run sensor_node (publishes 5 readings, most likely some > 27)
        sensor_result = _run_in_ns(
            [SENSOR_BIN, "-e", ROUTER_ENDPOINT, "-c", "5"],
            timeout=20,
        )

        # Wait for actuator to receive command
        try:
            act_stdout, act_stderr = act_proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            act_proc.kill()
            act_stdout, act_stderr = act_proc.communicate()

        print(f"\n  Sensor readings received: {len(sensor_readings)}")
        high_temps = [r for r in sensor_readings if r.get("value", 0) > 27.0]
        print(f"  High temp triggers: {len(high_temps)}")
        print(f"  Actuator stdout:\n{act_stdout[:500]}")

        assert sensor_result.returncode == 0
        assert len(sensor_readings) >= 3
        # sensor_node generates random temps 20-30, high chance of >27
        if high_temps:
            assert "SET" in act_stdout, "Actuator did not receive SET command"

        master.close()


# ---------------------------------------------------------------------------
# Test 5: tshark physical wire verification
# ---------------------------------------------------------------------------


@skip_unless_ready
class TestPhysicalWireVerification:
    """Verify with tshark that traffic actually traverses the 10BASE-T1S wire."""

    def test_tshark_captures_interop_traffic(self):
        """tshark on eth1 captures zenoh-pico → zenohd TCP packets."""
        pcap_file = "/tmp/interop_capture.pcap"

        # Start tshark capture on eth1
        tshark = subprocess.Popen(
            ["sudo", "tshark", "-i", "eth1", "-a", "duration:12",
             "-f", "tcp port 7447", "-w", pcap_file],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        time.sleep(1.0)

        # Run sensor_node in ns_slave (3 messages)
        _run_in_ns(
            [SENSOR_BIN, "-e", ROUTER_ENDPOINT, "-c", "3"],
            timeout=15,
        )

        # Wait for tshark to finish
        tshark.wait(timeout=20)

        # Analyze capture
        result = subprocess.run(
            ["sudo", "tshark", "-r", pcap_file, "-T", "fields",
             "-e", "ip.src", "-e", "ip.dst", "-e", "tcp.port"],
            capture_output=True, text=True, timeout=10,
        )

        print(f"\n  pcap: {pcap_file}")
        print(f"  Captured packets:\n{result.stdout[:1000]}")

        # Verify 192.168.1.2 (slave/eth2) traffic on eth1
        assert "192.168.1.2" in result.stdout, \
            "No slave (192.168.1.2) traffic captured on eth1 — not traversing physical wire"
        assert "192.168.1.1" in result.stdout, \
            "No master (192.168.1.1) traffic captured"

        master.close() if 'master' in dir() else None
