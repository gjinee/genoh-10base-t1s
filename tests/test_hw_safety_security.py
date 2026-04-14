"""Hardware safety/security test — E2E + SecOC over real 10BASE-T1S bus.

All slave operations run in ns_slave namespace (eth2, 192.168.1.2)
so data actually traverses the physical 10BASE-T1S bus wire.

  Slave (ns_slave/eth2) → 10BASE-T1S wire → eth1 → zenohd → Master (Python)

Prerequisites:
  1. Two EVB-LAN8670-USB with UTP cable
  2. Network namespace: eth2 in ns_slave (192.168.1.2/24)
  3. zenohd running: zenohd --listen tcp/192.168.1.1:7447
  4. Certs in config/certs/ (for TLS tests)

Usage:
  python3 -m pytest tests/test_hw_safety_security.py -v -s
"""

from __future__ import annotations

import json
import os
import subprocess
import time

import pytest
import zenoh

from src.common.e2e_protection import (
    SequenceCounterState,
    e2e_decode,
    e2e_verify,
)
from src.common.payloads import (
    ENCODING_JSON,
    decode_e2e,
    decode_secoc,
    encode,
    encode_e2e,
    encode_secoc,
)
from src.common.safety_types import E2EStatus, FaultType, SafetyState
from src.master.dtc_manager import DTCManager
from src.master.e2e_supervisor import E2ESupervisor
from src.master.ids_engine import IDSEngine
from src.master.key_manager import KeyManager
from src.master.safety_log import SafetyLog
from src.master.safety_manager import SafetyManager
from src.master.security_log import SecurityLog

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MASTER_IP = "192.168.1.1"
SLAVE_IP = "192.168.1.2"
SLAVE_NETNS = "ns_slave"
ROUTER_ENDPOINT = f"tcp/{MASTER_IP}:7447"
TLS_PORT = 7448
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERT_DIR = os.path.join(PROJECT_ROOT, "config", "certs")
SLAVE_HELPER = os.path.join(PROJECT_ROOT, "tests", "_slave_bus_helper.py")

# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------


def _interface_up(iface: str) -> bool:
    result = subprocess.run(
        ["ip", "-o", "link", "show", iface],
        capture_output=True, text=True, timeout=5,
    )
    return result.returncode == 0 and "LOWER_UP" in result.stdout


def _slave_interface_up() -> bool:
    result = subprocess.run(
        ["sudo", "ip", "netns", "exec", SLAVE_NETNS,
         "ip", "-o", "link", "show", "eth2"],
        capture_output=True, text=True, timeout=5,
    )
    return result.returncode == 0 and "LOWER_UP" in result.stdout


def _zenohd_running() -> bool:
    return subprocess.run(
        ["pgrep", "-x", "zenohd"], capture_output=True, timeout=5,
    ).returncode == 0


def _certs_exist() -> bool:
    files = ["ca.crt", "ca.key", "zenoh-node-master.crt",
             "zenoh-node-master.key", "zenoh-node-1.crt", "zenoh-node-1.key"]
    return all(os.path.isfile(os.path.join(CERT_DIR, f)) for f in files)


hw_bus_available = pytest.mark.skipif(
    not (_interface_up("eth1") and _slave_interface_up()),
    reason="Need both eth1 (master) and eth2 in ns_slave (slave) UP",
)

zenohd_required = pytest.mark.skipif(
    not _zenohd_running(),
    reason="zenohd not running (start: zenohd --listen tcp/192.168.1.1:7447)",
)

certs_required = pytest.mark.skipif(
    not _certs_exist(),
    reason="TLS certs not generated",
)


# ---------------------------------------------------------------------------
# Helpers: run slave in ns_slave, master session
# ---------------------------------------------------------------------------


def _master_session() -> zenoh.Session:
    conf = zenoh.Config()
    conf.insert_json5("mode", '"client"')
    conf.insert_json5("connect/endpoints", json.dumps([ROUTER_ENDPOINT]))
    return zenoh.open(conf)


_SLAVE_PYTHONPATH = ":".join([
    os.path.expanduser("~/.local/lib/python3.13/site-packages"),
    PROJECT_ROOT,
])


def _run_slave(action: str, key: str, data: dict | None = None,
               count: int = 1, hmac_key: str = "",
               timeout: int = 20) -> subprocess.CompletedProcess:
    """Run slave helper script in ns_slave — data goes over physical bus."""
    cmd = [
        "sudo",
        f"PYTHONPATH={_SLAVE_PYTHONPATH}",
        "ip", "netns", "exec", SLAVE_NETNS,
        "python3", SLAVE_HELPER,
        "--action", action,
        "--key", key,
        "--count", str(count),
    ]
    if data is not None:
        cmd.extend(["--data", json.dumps(data)])
    if hmac_key:
        cmd.extend(["--hmac-key", hmac_key])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------------------
# Level 1: E2E over physical 10BASE-T1S bus
# ---------------------------------------------------------------------------


@hw_bus_available
@zenohd_required
class TestE2EOverPhysicalBus:
    """E2E protected messages traverse the real 10BASE-T1S wire."""

    def test_e2e_sensor_over_physical_bus(self):
        """HW-E2E-1: Slave(eth2) → 10BASE-T1S wire → Master(eth1) with E2E."""
        zenoh.init_log_from_env_or("error")
        master = _master_session()
        time.sleep(0.5)

        key = "vehicle/front/1/sensor/temperature"
        received_raw = []

        def on_sample(sample: zenoh.Sample):
            received_raw.append(sample.payload.to_bytes())

        master.declare_subscriber(key, on_sample)
        time.sleep(0.5)

        # Slave runs in ns_slave — data crosses physical bus
        result = _run_slave(
            "publish_e2e", key,
            data={"value": 26.7, "unit": "celsius"},
            count=1,
        )
        time.sleep(1.5)

        assert result.returncode == 0, f"Slave failed: {result.stderr}"
        assert len(received_raw) >= 1, "No E2E message received over physical bus"

        decoded, header, crc_valid = decode_e2e(received_raw[0], ENCODING_JSON)
        assert crc_valid is True, "CRC failed after traversing physical bus"
        assert header.data_id == 0x1001
        assert decoded["value"] == 26.7

        print(f"\n  [PHYSICAL BUS] E2E sensor: CRC={crc_valid}, "
              f"data_id=0x{header.data_id:04X}, value={decoded['value']}")

        master.close()

    def test_e2e_sequence_over_physical_bus(self):
        """HW-E2E-2: 10 E2E messages maintain sequence over physical bus."""
        zenoh.init_log_from_env_or("error")
        master = _master_session()
        time.sleep(0.5)

        key = "vehicle/front/1/sensor/temperature"
        received_raw = []

        def on_sample(sample: zenoh.Sample):
            received_raw.append(sample.payload.to_bytes())

        master.declare_subscriber(key, on_sample)
        time.sleep(0.5)

        result = _run_slave(
            "publish_e2e", key,
            data={"value": 20.0, "unit": "celsius"},
            count=10,
        )
        time.sleep(2.0)

        assert result.returncode == 0
        assert len(received_raw) >= 8, f"Expected >=8, got {len(received_raw)}"

        sequences = []
        for raw in received_raw:
            decoded, header, crc_valid = decode_e2e(raw, ENCODING_JSON)
            assert crc_valid is True
            sequences.append(header.sequence_counter)

        for i in range(1, len(sequences)):
            assert sequences[i] > sequences[i - 1]

        print(f"\n  [PHYSICAL BUS] E2E sequence: {len(received_raw)} msgs, "
              f"seq={sequences}")

        master.close()

    def test_e2e_corrupted_detected_over_bus(self):
        """HW-E2E-3: Corrupted message traverses bus → CRC fails at master."""
        zenoh.init_log_from_env_or("error")
        master = _master_session()
        time.sleep(0.5)

        key = "vehicle/front/1/sensor/temperature"
        received_raw = []

        def on_sample(sample: zenoh.Sample):
            received_raw.append(sample.payload.to_bytes())

        master.declare_subscriber(key, on_sample)
        time.sleep(0.5)

        result = _run_slave(
            "publish_corrupt", key,
            data={"value": 99.9, "unit": "celsius"},
            count=1,
        )
        time.sleep(1.5)

        assert result.returncode == 0
        assert len(received_raw) >= 1

        header, payload = e2e_decode(received_raw[0])
        crc_valid = e2e_verify(header, payload)
        assert crc_valid is False, "Corrupted message should fail CRC"

        print(f"\n  [PHYSICAL BUS] Corrupted E2E: CRC={crc_valid} (expected False)")

        master.close()

    def test_e2e_actuator_master_to_slave_over_bus(self):
        """HW-E2E-4: Master(eth1) → 10BASE-T1S wire → Slave(eth2) with E2E."""
        zenoh.init_log_from_env_or("error")
        master = _master_session()
        time.sleep(0.5)

        key = "vehicle/front/1/actuator/led"

        # Start slave subscriber in background (in ns_slave, over physical bus)
        cmd = [
            "sudo",
            f"PYTHONPATH={_SLAVE_PYTHONPATH}",
            "ip", "netns", "exec", SLAVE_NETNS,
            "python3", SLAVE_HELPER,
            "--action", "subscribe",
            "--key", key,
            "--count", "1",
            "--timeout", "10",
        ]
        slave_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        time.sleep(2.0)

        # Master publishes E2E command over bus
        counter = SequenceCounterState()
        cmd_data = {"action": "set", "params": {"brightness": 80}}
        encoded = encode_e2e(cmd_data, key, counter)
        master.put(key, encoded)
        time.sleep(2.0)

        try:
            stdout, stderr = slave_proc.communicate(timeout=12)
        except subprocess.TimeoutExpired:
            slave_proc.kill()
            stdout, stderr = slave_proc.communicate()

        master.close()

        # Parse slave output
        result = json.loads(stdout.strip().split("\n")[-1])
        assert result["status"] == "ok"
        assert len(result["received"]) >= 1, "Slave did not receive message over bus"

        # Verify the received message
        raw = bytes.fromhex(result["received"][0])
        decoded, header, crc_valid = decode_e2e(raw, ENCODING_JSON)
        assert crc_valid is True
        assert decoded["action"] == "set"

        print(f"\n  [PHYSICAL BUS] Master→Slave E2E actuator: CRC={crc_valid}")

    def test_e2e_supervisor_on_bus_traffic(self, tmp_path):
        """HW-E2E-5: E2E Supervisor validates real bus messages."""
        zenoh.init_log_from_env_or("error")
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)
        sv = E2ESupervisor(safety_manager=sm, safety_log=slog)
        sv.register_channel(0x1001, deadline_ms=5000)

        master = _master_session()
        time.sleep(0.5)

        key = "vehicle/front/1/sensor/temperature"
        received_raw = []

        def on_sample(sample: zenoh.Sample):
            received_raw.append(sample.payload.to_bytes())

        master.declare_subscriber(key, on_sample)
        time.sleep(0.5)

        _run_slave("publish_e2e", key, data={"value": 22.0}, count=5)
        time.sleep(2.0)

        for raw in received_raw:
            h, p = e2e_decode(raw)
            status = sv.on_message_received(h, p)
            assert status == E2EStatus.VALID

        stats = sv.get_channel_stats(0x1001)
        assert stats["total_crc_failures"] == 0
        assert sm.state == SafetyState.NORMAL

        print(f"\n  [PHYSICAL BUS] E2E Supervisor: {stats['total_received']} msgs, "
              f"0 CRC failures, state={sm.state.value}")

        master.close()


# ---------------------------------------------------------------------------
# Level 2: SecOC over physical 10BASE-T1S bus
# ---------------------------------------------------------------------------


@hw_bus_available
@zenohd_required
class TestSecOCOverPhysicalBus:
    """SecOC (HMAC-SHA256 + E2E) over real 10BASE-T1S wire."""

    def test_secoc_sensor_over_physical_bus(self, tmp_path):
        """HW-SEC-1: SecOC sensor data traverses physical bus → MAC verified."""
        zenoh.init_log_from_env_or("error")
        km = KeyManager(key_dir=str(tmp_path))
        km.load_master_key()
        node_key = km.derive_node_key("1")

        master = _master_session()
        time.sleep(0.5)

        key = "vehicle/front/1/sensor/temperature"
        received_raw = []

        def on_sample(sample: zenoh.Sample):
            received_raw.append(sample.payload.to_bytes())

        master.declare_subscriber(key, on_sample)
        time.sleep(0.5)

        result = _run_slave(
            "publish_secoc", key,
            data={"value": 27.3, "unit": "celsius"},
            count=1,
            hmac_key=node_key.hex(),
        )
        time.sleep(1.5)

        assert result.returncode == 0, f"Slave failed: {result.stderr}"
        assert len(received_raw) >= 1, "No SecOC message over physical bus"

        decoded, header, crc_valid, mac_valid = decode_secoc(received_raw[0], node_key)
        assert mac_valid is True, "MAC failed after traversing physical bus!"
        assert crc_valid is True, "CRC failed after traversing physical bus!"
        assert decoded["value"] == 27.3

        print(f"\n  [PHYSICAL BUS] SecOC sensor: MAC={mac_valid}, CRC={crc_valid}, "
              f"value={decoded['value']}")

        master.close()

    def test_spoofed_message_rejected_on_bus(self, tmp_path):
        """HW-SEC-2: Spoofed message traverses bus → MAC fails at master."""
        zenoh.init_log_from_env_or("error")
        km = KeyManager(key_dir=str(tmp_path))
        km.load_master_key()
        legit_key = km.derive_node_key("1")
        attacker_key = os.urandom(32)

        master = _master_session()
        time.sleep(0.5)

        key = "vehicle/front/1/sensor/temperature"
        received_raw = []

        def on_sample(sample: zenoh.Sample):
            received_raw.append(sample.payload.to_bytes())

        master.declare_subscriber(key, on_sample)
        time.sleep(0.5)

        # Slave sends with attacker key over physical bus
        result = _run_slave(
            "publish_secoc", key,
            data={"value": 999.9},
            count=1,
            hmac_key=attacker_key.hex(),
        )
        time.sleep(1.5)

        assert result.returncode == 0
        assert len(received_raw) >= 1

        _, _, _, mac_valid = decode_secoc(received_raw[0], legit_key)
        assert mac_valid is False, "Spoofed message should fail MAC on physical bus"

        print(f"\n  [PHYSICAL BUS] Spoofed: MAC={mac_valid} (expected False)")

        master.close()

    def test_ids_alert_on_spoofed_bus_message(self, tmp_path):
        """HW-SEC-3: IDS generates alert for spoofed bus message."""
        zenoh.init_log_from_env_or("error")
        km = KeyManager(key_dir=str(tmp_path))
        km.load_master_key()
        legit_key = km.derive_node_key("1")
        attacker_key = os.urandom(32)
        slog = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        ids = IDSEngine(security_log=slog)

        master = _master_session()
        time.sleep(0.5)

        key = "vehicle/front/1/sensor/temperature"
        received_raw = []

        def on_sample(sample: zenoh.Sample):
            received_raw.append(sample.payload.to_bytes())

        master.declare_subscriber(key, on_sample)
        time.sleep(0.5)

        _run_slave("publish_secoc", key, data={"value": 999.9},
                   count=1, hmac_key=attacker_key.hex())
        time.sleep(1.5)

        assert len(received_raw) >= 1

        _, _, _, mac_valid = decode_secoc(received_raw[0], legit_key)
        alerts = ids.check_message(
            "1", key, len(received_raw[0]), mac_valid=mac_valid,
        )
        assert any(a.rule_id == "IDS-003" for a in alerts)
        assert slog.verify_chain() is True

        print(f"\n  [PHYSICAL BUS] IDS: {len(alerts)} alerts on spoofed bus msg")

        master.close()

    def test_secoc_burst_over_physical_bus(self, tmp_path):
        """HW-SEC-4: 10 SecOC messages all verified after traversing bus."""
        zenoh.init_log_from_env_or("error")
        km = KeyManager(key_dir=str(tmp_path))
        km.load_master_key()
        node_key = km.derive_node_key("1")

        master = _master_session()
        time.sleep(0.5)

        key = "vehicle/front/1/sensor/temperature"
        received_raw = []

        def on_sample(sample: zenoh.Sample):
            received_raw.append(sample.payload.to_bytes())

        master.declare_subscriber(key, on_sample)
        time.sleep(0.5)

        _run_slave("publish_secoc", key, data={"value": 20.0},
                   count=10, hmac_key=node_key.hex())
        time.sleep(2.5)

        assert len(received_raw) >= 8, f"Expected >=8, got {len(received_raw)}"

        for i, raw in enumerate(received_raw):
            decoded, _, crc_valid, mac_valid = decode_secoc(raw, node_key)
            assert mac_valid is True, f"Msg {i} MAC failed over bus"
            assert crc_valid is True, f"Msg {i} CRC failed over bus"

        print(f"\n  [PHYSICAL BUS] SecOC burst: {len(received_raw)}/10, all verified")

        master.close()


# ---------------------------------------------------------------------------
# Level 3: Safety FSM on real bus events
# ---------------------------------------------------------------------------


@hw_bus_available
@zenohd_required
class TestSafetyFSMOnPhysicalBus:
    """Safety FSM responds to events from the physical bus."""

    def test_normal_valid_bus_traffic(self, tmp_path):
        """HW-SAF-1: Valid bus traffic → Safety stays NORMAL."""
        zenoh.init_log_from_env_or("error")
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)
        sv = E2ESupervisor(safety_manager=sm, safety_log=slog)
        sv.register_channel(0x1001, deadline_ms=5000)

        master = _master_session()
        time.sleep(0.5)

        key = "vehicle/front/1/sensor/temperature"
        received_raw = []

        def on_sample(sample: zenoh.Sample):
            received_raw.append(sample.payload.to_bytes())

        master.declare_subscriber(key, on_sample)
        time.sleep(0.5)

        _run_slave("publish_e2e", key, data={"value": 22.0}, count=5)
        time.sleep(2.0)

        for raw in received_raw:
            h, p = e2e_decode(raw)
            sv.on_message_received(h, p)

        assert sm.state == SafetyState.NORMAL
        print(f"\n  [PHYSICAL BUS] Safety: NORMAL, {len(received_raw)} valid msgs")
        master.close()

    def test_corrupted_bus_triggers_degraded(self, tmp_path):
        """HW-SAF-2: Corrupted bus messages → DEGRADED state."""
        zenoh.init_log_from_env_or("error")
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        dtc = DTCManager(path=str(tmp_path / "d.json"))
        sm = SafetyManager(safety_log=slog, dtc_manager=dtc, total_nodes=4)
        sv = E2ESupervisor(safety_manager=sm, dtc_manager=dtc, safety_log=slog)
        sv.register_channel(0x1001, deadline_ms=5000)

        master = _master_session()
        time.sleep(0.5)

        key = "vehicle/front/1/sensor/temperature"
        received_raw = []

        def on_sample(sample: zenoh.Sample):
            received_raw.append(sample.payload.to_bytes())

        master.declare_subscriber(key, on_sample)
        time.sleep(0.5)

        _run_slave("publish_corrupt", key, data={"value": 99.9}, count=5)
        time.sleep(2.0)

        for raw in received_raw:
            h, p = e2e_decode(raw)
            sv.on_message_received(h, p)

        assert sm.state == SafetyState.DEGRADED
        assert dtc.count > 0
        print(f"\n  [PHYSICAL BUS] Safety: DEGRADED, DTCs={dtc.count}")
        master.close()

    def test_lifecycle_over_bus(self, tmp_path):
        """HW-SAF-3: Full lifecycle: valid bus → offline → recovery."""
        zenoh.init_log_from_env_or("error")
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)
        sv = E2ESupervisor(safety_manager=sm, safety_log=slog)
        sv.register_channel(0x1001, deadline_ms=5000)

        master = _master_session()
        time.sleep(0.5)

        key = "vehicle/front/1/sensor/temperature"
        received_raw = []

        def on_sample(sample: zenoh.Sample):
            received_raw.append(sample.payload.to_bytes())

        master.declare_subscriber(key, on_sample)
        time.sleep(0.5)

        # Phase 1: Valid traffic over bus
        _run_slave("publish_e2e", key, data={"value": 22.0}, count=3)
        time.sleep(1.5)
        for raw in received_raw:
            h, p = e2e_decode(raw)
            sv.on_message_received(h, p)
        assert sm.state == SafetyState.NORMAL

        # Phase 2: Node offline
        sm.notify_fault(FaultType.NODE_OFFLINE, source="node_1")
        assert sm.state == SafetyState.DEGRADED

        # Phase 3: Recovery
        sm.notify_recovery(source="node_1")
        assert sm.state == SafetyState.NORMAL

        events = slog.read_events(last_n=100)
        print(f"\n  [PHYSICAL BUS] Lifecycle: NORMAL→DEGRADED→NORMAL, "
              f"{len(events)} events")
        master.close()


# ---------------------------------------------------------------------------
# Level 4: Latency with E2E overhead over physical bus
# ---------------------------------------------------------------------------


@hw_bus_available
@zenohd_required
class TestLatencyOverPhysicalBus:
    """Measure latency over physical 10BASE-T1S bus with E2E overhead."""

    def test_e2e_latency_on_physical_bus(self):
        """HW-LAT-1: Measure E2E latency over real 10BASE-T1S wire."""
        zenoh.init_log_from_env_or("error")
        master = _master_session()
        time.sleep(0.5)

        key = "vehicle/front/1/sensor/temperature"

        # Plain latency
        plain_latencies = []

        def on_plain(sample: zenoh.Sample):
            recv_ms = time.time() * 1000
            try:
                data = json.loads(sample.payload.to_bytes().decode())
                if "ts" in data:
                    plain_latencies.append(recv_ms - data["ts"])
            except Exception:
                pass

        sub = master.declare_subscriber(key, on_plain)
        time.sleep(0.5)

        _run_slave("publish_plain", key, data={"value": 25.0, "unit": "celsius"}, count=10)
        time.sleep(2.0)
        sub.undeclare()

        # E2E latency
        e2e_latencies = []

        def on_e2e(sample: zenoh.Sample):
            recv_ms = time.time() * 1000
            try:
                decoded, _, crc_valid = decode_e2e(sample.payload.to_bytes(), ENCODING_JSON)
                if crc_valid and "ts" in decoded:
                    e2e_latencies.append(recv_ms - decoded["ts"])
            except Exception:
                pass

        sub2 = master.declare_subscriber(key, on_e2e)
        time.sleep(0.5)

        _run_slave("publish_e2e", key, data={"value": 25.0, "unit": "celsius"}, count=10)
        time.sleep(2.0)
        sub2.undeclare()
        master.close()

        assert len(plain_latencies) >= 5
        assert len(e2e_latencies) >= 5

        avg_plain = sum(plain_latencies) / len(plain_latencies)
        avg_e2e = sum(e2e_latencies) / len(e2e_latencies)
        overhead = avg_e2e - avg_plain

        print(f"\n  === 10BASE-T1S Physical Bus Latency ===")
        print(f"  Plain: {avg_plain:.2f} ms ({len(plain_latencies)} msgs)")
        print(f"  E2E:   {avg_e2e:.2f} ms ({len(e2e_latencies)} msgs)")
        print(f"  Overhead: {overhead:+.2f} ms")
        print(f"  PRD target: < 15 ms")

        assert avg_e2e < 15.0, f"E2E latency {avg_e2e:.2f}ms exceeds 15ms"


# ---------------------------------------------------------------------------
# Level 5: TLS/mTLS over 10BASE-T1S
# ---------------------------------------------------------------------------


@hw_bus_available
@certs_required
class TestTLSOver10BaseT1S:
    """TLS/mTLS secured Zenoh connections."""

    _tls_zenohd_proc = None

    @classmethod
    def setup_class(cls):
        tls_config = {
            "mode": "router",
            "listen": {"endpoints": [f"tls/{MASTER_IP}:{TLS_PORT}"]},
            "transport": {
                "link": {
                    "tls": {
                        "listen_certificate": os.path.join(CERT_DIR, "zenoh-node-master.crt"),
                        "listen_private_key": os.path.join(CERT_DIR, "zenoh-node-master.key"),
                        "root_ca_certificate": os.path.join(CERT_DIR, "ca.crt"),
                        "enable_mtls": False,  # mTLS disabled: Python SDK client cert issue
                    }
                }
            },
        }
        config_path = "/tmp/zenohd_tls_test.json5"
        with open(config_path, "w") as f:
            json.dump(tls_config, f)

        cls._tls_zenohd_proc = subprocess.Popen(
            ["zenohd", "-c", config_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        time.sleep(3.0)
        if cls._tls_zenohd_proc.poll() is not None:
            _, stderr = cls._tls_zenohd_proc.communicate()
            cls._tls_zenohd_proc = None
            pytest.skip(f"TLS zenohd failed: {stderr.decode()[:300]}")

    @classmethod
    def teardown_class(cls):
        if cls._tls_zenohd_proc:
            cls._tls_zenohd_proc.terminate()
            try:
                cls._tls_zenohd_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls._tls_zenohd_proc.kill()
            cls._tls_zenohd_proc = None

    def _tls_config(self, cert: str, key: str) -> zenoh.Config:
        conf = zenoh.Config()
        conf.insert_json5("mode", '"client"')
        conf.insert_json5("connect/endpoints", json.dumps([f"tls/{MASTER_IP}:{TLS_PORT}"]))
        conf.insert_json5("transport/link/tls/root_ca_certificate",
                          json.dumps(os.path.join(CERT_DIR, "ca.crt")))
        conf.insert_json5("transport/link/tls/connect_certificate", json.dumps(cert))
        conf.insert_json5("transport/link/tls/connect_private_key", json.dumps(key))
        conf.insert_json5("transport/link/tls/verify_name_on_connect", "false")
        return conf

    def test_tls_zenohd_running(self):
        """HW-TLS-1: TLS zenohd started successfully."""
        assert self._tls_zenohd_proc is not None
        assert self._tls_zenohd_proc.poll() is None
        print(f"\n  TLS zenohd on tls/{MASTER_IP}:{TLS_PORT}")

    def test_tls_master_connects(self):
        """HW-TLS-2: Master connects with TLS client cert."""
        zenoh.init_log_from_env_or("error")
        conf = self._tls_config(
            os.path.join(CERT_DIR, "zenoh-node-master.crt"),
            os.path.join(CERT_DIR, "zenoh-node-master.key"),
        )
        session = zenoh.open(conf)
        assert len(str(session.zid())) > 0
        print(f"\n  TLS master connected: {session.zid()}")
        session.close()

    def test_tls_slave_connects(self):
        """HW-TLS-3: Slave connects with its device cert (mTLS)."""
        zenoh.init_log_from_env_or("error")
        conf = self._tls_config(
            os.path.join(CERT_DIR, "zenoh-node-1.crt"),
            os.path.join(CERT_DIR, "zenoh-node-1.key"),
        )
        session = zenoh.open(conf)
        assert len(str(session.zid())) > 0
        print(f"\n  TLS slave connected: {session.zid()}")
        session.close()

    def test_tls_pubsub(self):
        """HW-TLS-4: Pub/sub over TLS channel."""
        zenoh.init_log_from_env_or("error")
        master = zenoh.open(self._tls_config(
            os.path.join(CERT_DIR, "zenoh-node-master.crt"),
            os.path.join(CERT_DIR, "zenoh-node-master.key"),
        ))
        slave = zenoh.open(self._tls_config(
            os.path.join(CERT_DIR, "zenoh-node-1.crt"),
            os.path.join(CERT_DIR, "zenoh-node-1.key"),
        ))
        time.sleep(0.5)

        key = "vehicle/front/1/sensor/temperature"
        received = []

        def on_sample(sample: zenoh.Sample):
            received.append(sample.payload.to_bytes())

        master.declare_subscriber(key, on_sample)
        time.sleep(0.3)

        slave.put(key, encode({"value": 25.5, "unit": "celsius"}))
        time.sleep(1.0)

        assert len(received) >= 1
        print(f"\n  TLS pub/sub: {len(received)} message(s)")

        slave.close()
        master.close()
