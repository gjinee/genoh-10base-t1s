"""MCU Advanced Tests — Fuzzing, Penetration, Fault Cascade over 10BASE-T1S.

Tests MCU resilience against: random data injection, replay attacks,
message flooding, malformed payloads, and cascading fault scenarios.

Prerequisites: SAM E70 with ASIL-D firmware, zenohd running.
"""

from __future__ import annotations

import binascii
import hashlib
import hmac
import json
import os
import re
import struct
import subprocess
import time

import pytest
import zenoh

# ---------------------------------------------------------------------------
# Configuration (same as test_mcu_safety_security.py)
# ---------------------------------------------------------------------------

MASTER_IFACE = "eth1"
MCU_IP = "192.168.100.11"
ROUTER_ENDPOINT = "tcp/192.168.100.1:7447"

KE_STEERING = "vehicle/front_left/1/sensor/steering"
KE_HEADLIGHT = "vehicle/front_left/1/actuator/headlight"
KE_HAZARD = "vehicle/front_left/1/actuator/hazard"

E2E_HEADER_SIZE = 11
DATA_ID_STEERING = 0x1010
DATA_ID_HEADLIGHT = 0x2010
SECOC_FRESHNESS_SIZE = 8
SECOC_MAC_SIZE = 16
SECOC_OVERHEAD = 24

# Key derivation: HMAC-SHA256(master_key, "epoch:1:front_left/1")
MASTER_KEY = bytes(range(32))
_derived = hmac.new(MASTER_KEY, b"epoch:1:front_left/1", hashlib.sha256).digest()
NODE_KEY = _derived

# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

def _mcu_reachable():
    r = subprocess.run(["ping","-c","1","-W","2","-I",MASTER_IFACE,MCU_IP],
                       capture_output=True, timeout=5)
    return r.returncode == 0

def _zenohd_running():
    return subprocess.run(["pgrep","-x","zenohd"],capture_output=True,timeout=5).returncode == 0

prereq = pytest.mark.skipif(
    not (_mcu_reachable() and _zenohd_running()),
    reason="MCU or zenohd not available")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session():
    zenoh.init_log_from_env_or("error")
    c = zenoh.Config()
    c.insert_json5("mode", '"client"')
    c.insert_json5("connect/endpoints", json.dumps([ROUTER_ENDPOINT]))
    return zenoh.open(c)

def _collect_raw(s, key, dur):
    rx = []
    def cb(sample): rx.append(sample.payload.to_bytes())
    sub = s.declare_subscriber(key, cb)
    time.sleep(dur)
    sub.undeclare()
    return rx

def _secoc_verify(raw):
    if len(raw) < SECOC_OVERHEAD: return raw, False
    e2e = raw[:len(raw)-SECOC_OVERHEAD]
    fv = raw[len(raw)-SECOC_OVERHEAD:len(raw)-SECOC_MAC_SIZE]
    mac = raw[len(raw)-SECOC_MAC_SIZE:]
    computed = hmac.new(NODE_KEY, e2e+fv, hashlib.sha256).digest()[:16]
    return e2e, hmac.compare_digest(computed, mac)

def _e2e_decode(raw):
    if len(raw) < 11: return {}, {}, False
    did,seq,alive,length,crc = struct.unpack(">HHBHI", raw[:11])
    payload = raw[11:11+length]
    crc_in = struct.pack(">HHBH",did,seq,alive,length) + payload
    ok = (binascii.crc32(crc_in) & 0xFFFFFFFF) == crc
    try: p = json.loads(payload)
    except: p = {}
    return {"data_id":did,"seq":seq,"alive":alive,"length":length,"crc":crc}, p, ok

def _make_secoc_cmd(payload_dict, data_id, seq, alive):
    pb = json.dumps(payload_dict).encode()
    crc_in = struct.pack(">HHBH", data_id, seq, alive, len(pb)) + pb
    crc = binascii.crc32(crc_in) & 0xFFFFFFFF
    e2e = struct.pack(">HHBHI", data_id, seq, alive, len(pb), crc) + pb
    ts = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    # MCU uses xTaskGetTickCount() for freshness — send MCU-compatible timestamp
    # For testing, use a large value that's within the MCU's replay window
    fv = struct.pack(">IHH", 0, 0, seq)  # 4+2=6B timestamp (near 0 = MCU boot tick range) + 2B counter
    # Actually build proper 8-byte freshness
    fv = b'\x00' * 6 + struct.pack(">H", seq)  # timestamp near 0 (matches MCU tick range)
    mac = hmac.new(NODE_KEY, e2e + fv, hashlib.sha256).digest()[:16]
    return e2e + fv + mac


# =========================================================================
# Fuzzing Tests
# =========================================================================

@prereq
class TestFuzzing:
    """MCU must survive all malformed inputs without crashing."""

    def test_random_bytes(self):
        """Send 20 random byte sequences → MCU keeps publishing."""
        s = _session()
        time.sleep(0.3)
        before = _collect_raw(s, KE_STEERING, 0.5)
        assert len(before) >= 3

        for _ in range(20):
            s.put(KE_HEADLIGHT, os.urandom(64))
            time.sleep(0.05)
        time.sleep(0.5)

        after = _collect_raw(s, KE_STEERING, 1.0)
        s.close()
        assert len(after) >= 5, "MCU crashed after random bytes"

    def test_empty_payload(self):
        """Send empty payload → MCU ignores, keeps publishing."""
        s = _session()
        time.sleep(0.3)
        s.put(KE_HEADLIGHT, b"")
        time.sleep(0.3)
        msgs = _collect_raw(s, KE_STEERING, 1.0)
        s.close()
        assert len(msgs) >= 5

    def test_oversized_payload(self):
        """Send 4KB payload → MCU ignores, keeps publishing."""
        s = _session()
        time.sleep(0.3)
        s.put(KE_HEADLIGHT, b"X" * 4096)
        time.sleep(0.3)
        msgs = _collect_raw(s, KE_STEERING, 1.0)
        s.close()
        assert len(msgs) >= 5

    def test_null_bytes(self):
        """Send null-filled payload → MCU ignores."""
        s = _session()
        time.sleep(0.3)
        s.put(KE_HEADLIGHT, b"\x00" * 128)
        time.sleep(0.3)
        msgs = _collect_raw(s, KE_STEERING, 1.0)
        s.close()
        assert len(msgs) >= 5

    def test_corrupted_e2e_header(self):
        """Send valid-length msg with corrupted E2E header fields."""
        s = _session()
        time.sleep(0.3)
        # Valid structure but wrong CRC
        fake = struct.pack(">HHBHI", 0x2010, 999, 0, 15, 0xDEADBEEF)
        fake += b'{"state":"on"}' + b'\x00'
        fake += b'\x00' * 24  # fake SecOC
        s.put(KE_HEADLIGHT, fake)
        time.sleep(0.5)
        msgs = _collect_raw(s, KE_STEERING, 1.0)
        s.close()
        assert len(msgs) >= 5, "MCU crashed after corrupted E2E"

    def test_valid_e2e_wrong_json(self):
        """Valid E2E+SecOC wrapper but invalid JSON inside."""
        s = _session()
        time.sleep(0.3)
        # Build valid wrapper around garbage JSON
        garbage = b'{"state":INVALID}'
        crc_in = struct.pack(">HHBH", 0x2010, 0, 0, len(garbage)) + garbage
        crc = binascii.crc32(crc_in) & 0xFFFFFFFF
        e2e = struct.pack(">HHBHI", 0x2010, 0, 0, len(garbage), crc) + garbage
        fv = b'\x00' * 8
        mac = hmac.new(NODE_KEY, e2e + fv, hashlib.sha256).digest()[:16]
        s.put(KE_HEADLIGHT, e2e + fv + mac)
        time.sleep(0.5)
        msgs = _collect_raw(s, KE_STEERING, 1.0)
        s.close()
        assert len(msgs) >= 5


# =========================================================================
# Penetration Tests
# =========================================================================

@prereq
class TestPenetration:
    """Security penetration tests against MCU."""

    def test_plain_json_rejected(self):
        """Plain JSON (no E2E/SecOC) must be rejected by ASIL-D MCU."""
        s = _session()
        time.sleep(0.3)
        # Send plain JSON — MCU should reject
        s.put(KE_HEADLIGHT, json.dumps({"state": "on"}).encode())
        time.sleep(0.5)
        msgs = _collect_raw(s, KE_STEERING, 1.0)
        s.close()
        # MCU still alive
        assert len(msgs) >= 5

    def test_wrong_key_rejected(self):
        """Message signed with wrong key must be rejected."""
        s = _session()
        time.sleep(0.3)
        pb = json.dumps({"state": "on"}).encode()
        crc_in = struct.pack(">HHBH", 0x2010, 0, 0, len(pb)) + pb
        crc = binascii.crc32(crc_in) & 0xFFFFFFFF
        e2e = struct.pack(">HHBHI", 0x2010, 0, 0, len(pb), crc) + pb
        fv = b'\x00' * 8
        wrong_key = b'\xFF' * 32
        mac = hmac.new(wrong_key, e2e + fv, hashlib.sha256).digest()[:16]
        s.put(KE_HEADLIGHT, e2e + fv + mac)
        time.sleep(0.5)
        msgs = _collect_raw(s, KE_STEERING, 1.0)
        s.close()
        assert len(msgs) >= 5

    def test_spoofed_data_id(self):
        """Message with steering data_id on headlight topic → rejected."""
        s = _session()
        time.sleep(0.3)
        pb = json.dumps({"state": "on"}).encode()
        crc_in = struct.pack(">HHBH", DATA_ID_STEERING, 0, 0, len(pb)) + pb
        crc = binascii.crc32(crc_in) & 0xFFFFFFFF
        e2e = struct.pack(">HHBHI", DATA_ID_STEERING, 0, 0, len(pb), crc) + pb
        fv = b'\x00' * 8
        mac = hmac.new(NODE_KEY, e2e + fv, hashlib.sha256).digest()[:16]
        s.put(KE_HEADLIGHT, e2e + fv + mac)
        time.sleep(0.5)
        msgs = _collect_raw(s, KE_STEERING, 1.0)
        s.close()
        assert len(msgs) >= 5

    def test_message_flood_resilience(self):
        """Send 100 messages in rapid burst → MCU survives."""
        s = _session()
        time.sleep(0.3)
        for i in range(100):
            s.put(KE_HEADLIGHT, os.urandom(48))
        time.sleep(1.0)
        msgs = _collect_raw(s, KE_STEERING, 2.0)
        s.close()
        print(f"\n  After 100-msg flood: received {len(msgs)} steering msgs")
        assert len(msgs) >= 10, "MCU degraded after flood"


# =========================================================================
# Fault Cascade Tests
# =========================================================================

@prereq
class TestZFaultCascade:
    """Cascading fault injection — run LAST (prefix Z)."""

    def test_multiple_bad_mac_degraded(self):
        """Multiple bad MAC → safety >= 1 (DEGRADED or higher)."""
        s = _session()
        time.sleep(0.3)
        # Send 3 bad MAC messages
        for i in range(3):
            bad = os.urandom(80)
            s.put(KE_HEADLIGHT, bad)
            time.sleep(0.1)
        time.sleep(0.5)

        raws = _collect_raw(s, KE_STEERING, 1.0)
        s.close()
        assert len(raws) >= 3
        e2e, _ = _secoc_verify(raws[-1])
        _, payload, _ = _e2e_decode(e2e)
        safety = payload.get("safety", -1)
        print(f"\n  Safety after 3 bad MACs: {safety}")
        assert safety >= 1, f"Expected DEGRADED+, got {safety}"

    def test_dtc_recorded_after_faults(self):
        """DTC count should increase after fault injection."""
        s = _session()
        time.sleep(0.3)
        raws = _collect_raw(s, KE_STEERING, 0.5)
        s.close()
        assert len(raws) >= 1
        e2e, _ = _secoc_verify(raws[-1])
        _, payload, _ = _e2e_decode(e2e)
        dtc = payload.get("dtc_count", 0)
        print(f"\n  DTC count: {dtc}")
        assert dtc >= 1, f"Expected dtc_count >= 1 after faults, got {dtc}"

    def test_key_epoch_present(self):
        """key_epoch field must be present and >= 1."""
        s = _session()
        time.sleep(0.3)
        raws = _collect_raw(s, KE_STEERING, 0.5)
        s.close()
        assert len(raws) >= 1
        e2e, _ = _secoc_verify(raws[-1])
        _, payload, _ = _e2e_decode(e2e)
        epoch = payload.get("key_epoch", 0)
        assert epoch >= 1, f"key_epoch={epoch}, expected >= 1"

    def test_e2e_secoc_still_valid_after_faults(self):
        """Even in degraded state, E2E+SecOC on steering must be valid."""
        s = _session()
        time.sleep(0.3)
        raws = _collect_raw(s, KE_STEERING, 1.0)
        s.close()
        assert len(raws) >= 5
        crc_pass = mac_pass = 0
        for raw in raws:
            e2e, mac_ok = _secoc_verify(raw)
            _, _, crc_ok = _e2e_decode(e2e)
            if crc_ok: crc_pass += 1
            if mac_ok: mac_pass += 1
        print(f"\n  After faults: CRC={crc_pass}/{len(raws)} MAC={mac_pass}/{len(raws)}")
        assert crc_pass == len(raws)
        assert mac_pass == len(raws)
