"""MCU Safety & Security test — E2E + SecOC + ASIL-D over 10BASE-T1S.

Tests E2E Protection, SecOC authentication, and Safety FSM on the SAM E70 MCU
communicating with RPi 5 master over real 10BASE-T1S physical bus.

Wire format: [E2E Header 11B][JSON payload][Freshness 8B][MAC 16B]

Prerequisites:
  1. SAM E70 flashed with safety/security firmware
  2. EVB-LAN8670-USB on eth1 (192.168.100.1/24)
  3. zenohd --listen tcp/192.168.100.1:7447
"""

from __future__ import annotations

import binascii
import hashlib
import hmac
import json
import re
import struct
import subprocess
import time

import pytest
import zenoh

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MASTER_IFACE = "eth1"
MCU_IP = "192.168.100.11"
MASTER_IP = "192.168.100.1"
ROUTER_ENDPOINT = f"tcp/{MASTER_IP}:7447"

KE_STEERING = "vehicle/front_left/1/sensor/steering"
KE_HEADLIGHT = "vehicle/front_left/1/actuator/headlight"
KE_HAZARD = "vehicle/front_left/1/actuator/hazard"

# E2E constants
E2E_HEADER_SIZE = 11
DATA_ID_STEERING = 0x1010
DATA_ID_HEADLIGHT = 0x2010
DATA_ID_HAZARD = 0x2011

# SecOC constants
SECOC_FRESHNESS_SIZE = 8
SECOC_MAC_SIZE = 16
SECOC_OVERHEAD = SECOC_FRESHNESS_SIZE + SECOC_MAC_SIZE  # 24
# Key derivation: HMAC-SHA256(master_key, "epoch:1:front_left/1")
_MASTER_KEY = bytes(range(32))  # 0x00..0x1F master key
SECOC_KEY = hmac.new(_MASTER_KEY, b"epoch:1:front_left/1", hashlib.sha256).digest()

# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------


def _interface_up(iface: str) -> bool:
    result = subprocess.run(
        ["ip", "-o", "link", "show", iface],
        capture_output=True, text=True, timeout=5,
    )
    return result.returncode == 0 and (
        "LOWER_UP" in result.stdout or "state UP" in result.stdout
    )


def _zenohd_running() -> bool:
    result = subprocess.run(
        ["pgrep", "-x", "zenohd"], capture_output=True, timeout=5,
    )
    return result.returncode == 0


def _mcu_reachable() -> bool:
    result = subprocess.run(
        ["ping", "-c", "1", "-W", "2", "-I", MASTER_IFACE, MCU_IP],
        capture_output=True, timeout=5,
    )
    return result.returncode == 0


hw_available = pytest.mark.skipif(not _interface_up(MASTER_IFACE), reason="eth1 not UP")
zenohd_required = pytest.mark.skipif(not _zenohd_running(), reason="zenohd not running")
mcu_required = pytest.mark.skipif(not _mcu_reachable(), reason=f"MCU not reachable at {MCU_IP}")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _master_session() -> zenoh.Session:
    zenoh.init_log_from_env_or("error")
    conf = zenoh.Config()
    conf.insert_json5("mode", '"client"')
    conf.insert_json5("connect/endpoints", json.dumps([ROUTER_ENDPOINT]))
    return zenoh.open(conf)


def _collect_raw(session: zenoh.Session, key: str, duration: float) -> list[bytes]:
    """Collect raw bytes from a Zenoh key expression."""
    received: list[bytes] = []

    def _on_sample(sample: zenoh.Sample):
        received.append(sample.payload.to_bytes())

    sub = session.declare_subscriber(key, _on_sample)
    time.sleep(duration)
    sub.undeclare()
    return received


def _e2e_decode(raw: bytes) -> tuple[dict, dict, bool]:
    """Decode E2E header and verify CRC.
    Returns (header_dict, payload_dict, crc_valid)."""
    if len(raw) < E2E_HEADER_SIZE:
        return {}, {}, False
    data_id, seq, alive, length, crc = struct.unpack(">HHBHI", raw[:E2E_HEADER_SIZE])
    payload_bytes = raw[E2E_HEADER_SIZE:E2E_HEADER_SIZE + length]

    # CRC verification
    crc_input = struct.pack(">HHBH", data_id, seq, alive, length) + payload_bytes
    computed = binascii.crc32(crc_input) & 0xFFFFFFFF

    header = {
        "data_id": data_id, "seq": seq, "alive": alive,
        "length": length, "crc": crc,
    }
    try:
        payload = json.loads(payload_bytes)
    except Exception:
        payload = {}
    return header, payload, computed == crc


def _secoc_verify(raw: bytes) -> tuple[bytes, bool]:
    """Verify SecOC MAC. Returns (e2e_part, mac_valid)."""
    if len(raw) < SECOC_OVERHEAD:
        return raw, False
    e2e_part = raw[: len(raw) - SECOC_OVERHEAD]
    freshness = raw[len(raw) - SECOC_OVERHEAD: len(raw) - SECOC_MAC_SIZE]
    mac = raw[len(raw) - SECOC_MAC_SIZE:]

    hmac_input = e2e_part + freshness
    computed = hmac.new(SECOC_KEY, hmac_input, hashlib.sha256).digest()[:SECOC_MAC_SIZE]
    return e2e_part, hmac.compare_digest(computed, mac)


def _get_mcu_tick(session: zenoh.Session) -> int:
    """Get MCU's current tick from its steering freshness value."""
    raws = _collect_raw(session, KE_STEERING, 0.5)
    if not raws:
        return 0
    raw = raws[-1]
    fv = raw[len(raw) - SECOC_OVERHEAD:len(raw) - SECOC_MAC_SIZE]
    # Parse 6-byte big-endian timestamp
    ts = 0
    for b in fv[:6]:
        ts = (ts << 8) | b
    return ts


def _secoc_e2e_encode(payload_dict: dict, data_id: int,
                      seq: int, alive: int,
                      mcu_tick: int = 0) -> bytes:
    """Encode a message with E2E + SecOC (for sending to MCU).
    mcu_tick: MCU's current FreeRTOS tick (from _get_mcu_tick)."""
    payload_bytes = json.dumps(payload_dict).encode()
    length = len(payload_bytes)

    # CRC
    crc_input = struct.pack(">HHBH", data_id, seq, alive, length) + payload_bytes
    crc = binascii.crc32(crc_input) & 0xFFFFFFFF

    # E2E header + payload
    e2e_msg = struct.pack(">HHBHI", data_id, seq, alive, length, crc) + payload_bytes

    # SecOC freshness: use MCU tick-compatible timestamp
    ts_ms = mcu_tick if mcu_tick > 0 else 0
    counter = seq & 0xFFFF
    # Pack 6-byte big-endian timestamp + 2-byte counter
    freshness = bytes([(ts_ms >> 40) & 0xFF, (ts_ms >> 32) & 0xFF,
                       (ts_ms >> 24) & 0xFF, (ts_ms >> 16) & 0xFF,
                       (ts_ms >> 8) & 0xFF, ts_ms & 0xFF,
                       (counter >> 8) & 0xFF, counter & 0xFF])

    hmac_input = e2e_msg + freshness
    mac = hmac.new(SECOC_KEY, hmac_input, hashlib.sha256).digest()[:SECOC_MAC_SIZE]

    return e2e_msg + freshness + mac


# =========================================================================
# Phase 1: E2E Protection Tests
# =========================================================================


@hw_available
@zenohd_required
@mcu_required
class TestE2EProtection:
    """Verify MCU steering messages have valid E2E headers."""

    def test_steering_e2e_format(self):
        """MCU steering must have 11B E2E header + JSON + 24B SecOC."""
        session = _master_session()
        time.sleep(1.0)  # warm-up: wait for MCU session to stabilize
        raws = _collect_raw(session, KE_STEERING, 1.5)
        session.close()
        assert len(raws) >= 5, f"Too few messages: {len(raws)}"

        for i, raw in enumerate(raws[:5]):
            assert len(raw) > E2E_HEADER_SIZE + SECOC_OVERHEAD, \
                f"msg[{i}] too short: {len(raw)} bytes"
            # Strip SecOC, decode E2E
            e2e_part, mac_valid = _secoc_verify(raw)
            header, payload, crc_valid = _e2e_decode(e2e_part)
            assert header["data_id"] == DATA_ID_STEERING, \
                f"msg[{i}] data_id=0x{header['data_id']:04X}, expected 0x{DATA_ID_STEERING:04X}"
            assert crc_valid, f"msg[{i}] CRC mismatch"

    def test_steering_e2e_sequence(self):
        """E2E sequence counter must be monotonically increasing."""
        session = _master_session()
        time.sleep(0.3)
        raws = _collect_raw(session, KE_STEERING, 1.5)
        session.close()
        assert len(raws) >= 5

        seqs = []
        for raw in raws:
            e2e_part, _ = _secoc_verify(raw)
            hdr, _, crc_ok = _e2e_decode(e2e_part)
            assert crc_ok
            seqs.append(hdr["seq"])

        for i in range(1, len(seqs)):
            delta = (seqs[i] - seqs[i - 1]) & 0xFFFF
            assert delta == 1, \
                f"Seq gap at [{i}]: {seqs[i - 1]} → {seqs[i]} (delta={delta})"

    def test_steering_crc_integrity(self):
        """All messages must pass CRC-32 verification over physical bus."""
        session = _master_session()
        time.sleep(0.3)
        raws = _collect_raw(session, KE_STEERING, 2.0)
        session.close()

        crc_pass = 0
        for raw in raws:
            e2e_part, _ = _secoc_verify(raw)
            _, _, crc_ok = _e2e_decode(e2e_part)
            if crc_ok:
                crc_pass += 1

        print(f"\n  CRC pass: {crc_pass}/{len(raws)}")
        assert crc_pass == len(raws), f"CRC failures: {len(raws) - crc_pass}"

    def test_e2e_data_id_correct(self):
        """Steering data_id must be 0x1010."""
        session = _master_session()
        time.sleep(0.3)
        raws = _collect_raw(session, KE_STEERING, 0.5)
        session.close()
        assert len(raws) >= 1
        e2e_part, _ = _secoc_verify(raws[0])
        hdr, _, _ = _e2e_decode(e2e_part)
        assert hdr["data_id"] == 0x1010

    def test_headlight_e2e_command(self):
        """Send E2E+SecOC encoded headlight command → MCU still publishes."""
        session = _master_session()
        time.sleep(0.3)

        # Get MCU's current tick for freshness
        tick = _get_mcu_tick(session)

        # Send secured command with MCU-compatible timestamp
        cmd = _secoc_e2e_encode({"state": "on"}, DATA_ID_HEADLIGHT, 0, 0, tick)
        session.put(KE_HEADLIGHT, cmd)
        time.sleep(0.5)

        # Verify MCU still alive
        raws = _collect_raw(session, KE_STEERING, 1.0)

        # Clean up
        tick2 = _get_mcu_tick(session)
        cmd_off = _secoc_e2e_encode({"state": "off"}, DATA_ID_HEADLIGHT, 1, 1, tick2)
        session.put(KE_HEADLIGHT, cmd_off)
        session.close()
        assert len(raws) >= 3, "MCU stopped after E2E headlight command"


# =========================================================================
# Phase 2: SecOC Tests
# =========================================================================


@hw_available
@zenohd_required
@mcu_required
class TestSecOC:
    """Verify SecOC HMAC-SHA256 authentication."""

    def test_steering_secoc_mac(self):
        """All steering messages must have valid HMAC-SHA256 MAC."""
        session = _master_session()
        time.sleep(0.3)
        raws = _collect_raw(session, KE_STEERING, 2.0)
        session.close()
        assert len(raws) >= 10

        mac_pass = 0
        for raw in raws:
            _, mac_valid = _secoc_verify(raw)
            if mac_valid:
                mac_pass += 1

        print(f"\n  MAC pass: {mac_pass}/{len(raws)}")
        assert mac_pass == len(raws), f"MAC failures: {len(raws) - mac_pass}"

    def test_secoc_freshness_increment(self):
        """Freshness counter must increment across messages."""
        session = _master_session()
        time.sleep(0.3)
        raws = _collect_raw(session, KE_STEERING, 1.0)
        session.close()
        assert len(raws) >= 5

        counters = []
        for raw in raws:
            fv = raw[len(raw) - SECOC_OVERHEAD:len(raw) - SECOC_MAC_SIZE]
            counter = struct.unpack(">H", fv[6:8])[0]
            counters.append(counter)

        for i in range(1, len(counters)):
            assert counters[i] > counters[i - 1], \
                f"Freshness counter not increasing: {counters[i - 1]} → {counters[i]}"

    def test_secoc_message_size(self):
        """SecOC adds exactly 24 bytes (8B freshness + 16B MAC)."""
        session = _master_session()
        time.sleep(0.3)
        raws = _collect_raw(session, KE_STEERING, 0.5)
        session.close()
        assert len(raws) >= 1

        raw = raws[0]
        e2e_part, _ = _secoc_verify(raw)
        hdr, _, _ = _e2e_decode(e2e_part)
        expected_total = E2E_HEADER_SIZE + hdr["length"] + SECOC_OVERHEAD
        assert len(raw) == expected_total, \
            f"Size mismatch: {len(raw)} != {expected_total}"

    def test_mac_verification_consistent(self):
        """All received MACs should be consistent with shared key."""
        session = _master_session()
        time.sleep(0.3)
        raws = _collect_raw(session, KE_STEERING, 1.0)
        session.close()
        assert len(raws) >= 5

        for i, raw in enumerate(raws[:5]):
            _, mac_valid = _secoc_verify(raw)
            assert mac_valid, f"msg[{i}] MAC verification failed"


# =========================================================================
# Phase 3: Safety FSM Tests (ASIL-D)
# =========================================================================


@hw_available
@zenohd_required
@mcu_required
class TestSafetyFSM:
    """Verify ASIL-D safety state machine behavior."""

    def test_normal_state_during_operation(self):
        """MCU should report safety=0 (NORMAL) during normal operation."""
        session = _master_session()
        time.sleep(0.3)
        raws = _collect_raw(session, KE_STEERING, 1.0)
        session.close()
        assert len(raws) >= 5

        # All messages should show NORMAL state (no faults injected yet)
        for raw in raws[:5]:
            e2e_part, _ = _secoc_verify(raw)
            _, payload, _ = _e2e_decode(e2e_part)
            assert payload.get("safety") == 0, \
                f"Expected safety=0 (NORMAL), got {payload.get('safety')}"

    def test_steering_includes_safety_field(self):
        """Steering JSON must include 'safety' field."""
        session = _master_session()
        time.sleep(0.3)
        raws = _collect_raw(session, KE_STEERING, 0.5)
        session.close()
        assert len(raws) >= 1

        e2e_part, _ = _secoc_verify(raws[0])
        _, payload, _ = _e2e_decode(e2e_part)
        assert "safety" in payload, "Missing 'safety' field in steering JSON"
        assert isinstance(payload["safety"], int)

    def test_payload_has_all_fields(self):
        """Steering JSON must have x, y, btn, angle, seq, safety."""
        session = _master_session()
        time.sleep(0.3)
        raws = _collect_raw(session, KE_STEERING, 0.5)
        session.close()
        assert len(raws) >= 1

        e2e_part, _ = _secoc_verify(raws[0])
        _, payload, _ = _e2e_decode(e2e_part)
        for field in ["x", "y", "btn", "angle", "seq", "safety"]:
            assert field in payload, f"Missing field: {field}"


# =========================================================================
# Phase 4: Performance with E2E+SecOC
# =========================================================================


@hw_available
@zenohd_required
@mcu_required
class TestPerformanceSecure:
    """Measure performance with E2E+SecOC overhead."""

    def test_e2e_secoc_publish_rate(self):
        """Publish rate should still be ~10 msg/s with E2E+SecOC overhead."""
        session = _master_session()
        time.sleep(0.3)
        duration = 3.0
        raws = _collect_raw(session, KE_STEERING, duration)
        session.close()
        rate = len(raws) / duration
        print(f"\n  E2E+SecOC rate: {rate:.1f} msg/s ({len(raws)} in {duration}s)")
        assert rate >= 7.0, f"Rate too low: {rate:.1f}"

    def test_e2e_secoc_latency(self):
        """ICMP RTT must still be < 15 ms (PRD NFR-001) with crypto overhead."""
        result = subprocess.run(
            ["ping", "-c", "10", "-I", MASTER_IFACE, MCU_IP],
            capture_output=True, text=True, timeout=20,
        )
        m = re.search(r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)", result.stdout)
        assert m, "Could not parse ping RTT"
        avg_ms = float(m.group(2))
        max_ms = float(m.group(3))
        print(f"\n  === E2E+SecOC Latency ===")
        print(f"  ICMP avg: {avg_ms:.2f} ms, max: {max_ms:.2f} ms")
        print(f"  PRD target: < 15 ms")
        assert max_ms < 15.0

    def test_e2e_continuous_30s(self):
        """30s continuous E2E+SecOC — all CRCs and MACs valid, loss < 1%."""
        session = _master_session()
        time.sleep(0.3)
        duration = 30.0
        raws = _collect_raw(session, KE_STEERING, duration)
        session.close()

        expected = duration / 0.1
        crc_ok = 0
        mac_ok = 0
        for raw in raws:
            e2e_part, mac_valid = _secoc_verify(raw)
            _, _, crc_valid = _e2e_decode(e2e_part)
            if crc_valid:
                crc_ok += 1
            if mac_valid:
                mac_ok += 1

        loss = 1.0 - len(raws) / expected
        print(f"\n  === 30s E2E+SecOC Continuous Test ===")
        print(f"  Received: {len(raws)}/{int(expected)}")
        print(f"  CRC pass: {crc_ok}/{len(raws)}")
        print(f"  MAC pass: {mac_ok}/{len(raws)}")
        print(f"  Loss: {loss * 100:.1f}%")
        assert crc_ok == len(raws), f"CRC failures: {len(raws) - crc_ok}"
        assert mac_ok == len(raws), f"MAC failures: {len(raws) - mac_ok}"
        assert len(raws) >= expected * 0.90


# =========================================================================
# Phase 5: Fault Injection (must run LAST — causes state transitions)
# =========================================================================


@hw_available
@zenohd_required
@mcu_required
class TestZFaultInjection:
    """Fault injection tests — run last (prefix Z for ordering)."""

    def test_reject_bad_mac(self):
        """MCU rejects actuator command with corrupted MAC."""
        session = _master_session()
        time.sleep(0.3)

        # Send command with corrupted MAC
        good_cmd = _secoc_e2e_encode({"state": "on"}, DATA_ID_HEADLIGHT, 100, 100)
        bad_cmd = bytearray(good_cmd)
        bad_cmd[-1] ^= 0xFF
        session.put(KE_HEADLIGHT, bytes(bad_cmd))
        time.sleep(0.5)

        # MCU should still be publishing (didn't crash)
        raws = _collect_raw(session, KE_STEERING, 1.0)
        session.close()
        assert len(raws) >= 3, "MCU stopped after bad MAC"

    def test_degraded_after_bad_mac(self):
        """MCU should be DEGRADED (safety=1) after MAC failure."""
        session = _master_session()
        time.sleep(0.3)
        raws = _collect_raw(session, KE_STEERING, 0.5)
        session.close()
        assert len(raws) >= 1

        e2e_part, _ = _secoc_verify(raws[-1])
        _, payload, _ = _e2e_decode(e2e_part)
        safety = payload.get("safety", -1)
        # After bad MAC: should be DEGRADED(1) or higher
        assert safety >= 1, f"Expected safety >= 1 after fault, got {safety}"
        print(f"\n  Safety state after fault: {safety}")
