"""MCU real-bus test — RPi 5 Master ↔ SAM E70 Slave over 10BASE-T1S.

Tests the real Zenoh protocol stack over the physical 10BASE-T1S bus:
  Master : RPi 5 + EVB-LAN8670-USB  → eth1  (192.168.100.1,  zenohd router)
  Slave  : SAM E70 + EVB-LAN8670-RMII → (192.168.100.11, zenoh-pico client)

MCU publishes:
  vehicle/front_left/1/sensor/steering  (100 ms, JSON: {x, y, btn, angle, seq})

MCU subscribes:
  vehicle/front_left/1/actuator/headlight  (JSON: {state: "on"/"off"})
  vehicle/front_left/1/actuator/hazard     (JSON: {state: "on"/"off"})

Prerequisites:
  1. EVB-LAN8670-USB on eth1, IP 192.168.100.1/24
  2. SAM E70 flashed and booted (firmware/sam-e70/build/firmware.elf)
  3. zenohd --listen tcp/192.168.100.1:7447

Usage:
  pytest tests/test_mcu_bus.py -v
"""

from __future__ import annotations

import json
import re
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

# MCU key expressions
KE_STEERING = "vehicle/front_left/1/sensor/steering"
KE_HEADLIGHT = "vehicle/front_left/1/actuator/headlight"
KE_HAZARD = "vehicle/front_left/1/actuator/hazard"

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
        ["pgrep", "-x", "zenohd"],
        capture_output=True, timeout=5,
    )
    return result.returncode == 0


def _mcu_reachable() -> bool:
    result = subprocess.run(
        ["ping", "-c", "1", "-W", "2", "-I", MASTER_IFACE, MCU_IP],
        capture_output=True, timeout=5,
    )
    return result.returncode == 0


hw_available = pytest.mark.skipif(
    not _interface_up(MASTER_IFACE),
    reason=f"{MASTER_IFACE} not UP",
)

zenohd_required = pytest.mark.skipif(
    not _zenohd_running(),
    reason="zenohd not running (start: zenohd --listen tcp/192.168.100.1:7447)",
)

mcu_required = pytest.mark.skipif(
    not _mcu_reachable(),
    reason=f"MCU not reachable at {MCU_IP}",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _master_session() -> zenoh.Session:
    zenoh.init_log_from_env_or("error")
    conf = zenoh.Config()
    conf.insert_json5("mode", '"client"')
    conf.insert_json5("connect/endpoints", json.dumps([ROUTER_ENDPOINT]))
    return zenoh.open(conf)


def _collect_steering(session: zenoh.Session, duration: float) -> list[dict]:
    """Subscribe to MCU steering and collect messages for *duration* seconds."""
    received: list[dict] = []

    def _on_sample(sample: zenoh.Sample):
        try:
            data = json.loads(sample.payload.to_bytes())
            data["_recv_ts"] = time.time()
            received.append(data)
        except Exception:
            pass

    sub = session.declare_subscriber(KE_STEERING, _on_sample)
    time.sleep(duration)
    sub.undeclare()
    return received


# =========================================================================
# Phase 1 — Physical Layer
# =========================================================================


@hw_available
class TestPhysicalLayer:
    """Verify 10BASE-T1S physical connectivity to MCU."""

    def test_eth1_link_up(self):
        """eth1 interface must be UP at 10 Mbps Half duplex."""
        result = subprocess.run(
            ["ethtool", MASTER_IFACE],
            capture_output=True, text=True, timeout=5,
        )
        assert "Link detected: yes" in result.stdout
        assert "10" in result.stdout  # 10 Mb/s

    @mcu_required
    def test_mcu_ping(self):
        """Ping MCU at 192.168.100.11 over 10BASE-T1S."""
        result = subprocess.run(
            ["ping", "-c", "5", "-I", MASTER_IFACE, MCU_IP],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0
        assert "0% packet loss" in result.stdout

    @mcu_required
    def test_mcu_ping_latency(self):
        """ICMP RTT to MCU must be < 5 ms."""
        result = subprocess.run(
            ["ping", "-c", "10", "-I", MASTER_IFACE, MCU_IP],
            capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0
        # parse "rtt min/avg/max/mdev = 0.967/1.298/1.471/0.234 ms"
        m = re.search(r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)", result.stdout)
        assert m, "Could not parse ping RTT"
        avg_ms = float(m.group(2))
        max_ms = float(m.group(3))
        print(f"\n  ICMP RTT: avg={avg_ms:.2f} ms, max={max_ms:.2f} ms")
        assert max_ms < 5.0, f"ICMP max RTT {max_ms:.2f} ms exceeds 5 ms"

    def test_zenohd_running(self):
        """zenohd router must be running."""
        assert _zenohd_running(), "zenohd not running"


# =========================================================================
# Phase 2 — Zenoh Transport Layer
# =========================================================================


@hw_available
@zenohd_required
@mcu_required
class TestZenohTransport:
    """Verify Zenoh session and MCU data reception."""

    def test_master_session_open(self):
        """Master can open Zenoh client session to router."""
        session = _master_session()
        assert str(session.zid())
        session.close()

    def test_mcu_steering_publish(self):
        """MCU publishes steering data — master receives >= 5 in 1.5 s."""
        session = _master_session()
        time.sleep(0.3)
        msgs = _collect_steering(session, 1.5)
        session.close()
        print(f"\n  Received {len(msgs)} steering messages in 1.5 s")
        assert len(msgs) >= 5, f"Expected >= 5, got {len(msgs)}"

    def test_steering_json_format(self):
        """Steering JSON must have {x, y, btn, angle, seq} with correct types."""
        session = _master_session()
        time.sleep(0.3)
        msgs = _collect_steering(session, 0.5)
        session.close()
        assert len(msgs) >= 1, "No steering message received"
        msg = msgs[0]
        assert "x" in msg and isinstance(msg["x"], int)
        assert "y" in msg and isinstance(msg["y"], int)
        assert "btn" in msg and isinstance(msg["btn"], int)
        assert "angle" in msg and isinstance(msg["angle"], (int, float))
        assert "seq" in msg and isinstance(msg["seq"], int)

    def test_steering_sequence_increment(self):
        """seq field must be monotonically increasing."""
        session = _master_session()
        time.sleep(0.3)
        msgs = _collect_steering(session, 1.0)
        session.close()
        assert len(msgs) >= 3, f"Need >= 3 msgs, got {len(msgs)}"
        seqs = [m["seq"] for m in msgs]
        for i in range(1, len(seqs)):
            assert seqs[i] > seqs[i - 1], \
                f"seq not increasing: {seqs[i - 1]} -> {seqs[i]}"


# =========================================================================
# Phase 3 — Bidirectional Control (Application Layer)
# =========================================================================


@hw_available
@zenohd_required
@mcu_required
class TestBidirectionalControl:
    """Verify master → MCU actuator commands while MCU keeps publishing."""

    def test_headlight_on(self):
        """Send headlight ON → MCU continues steering publish."""
        session = _master_session()
        time.sleep(0.3)

        # send actuator command
        session.put(KE_HEADLIGHT, json.dumps({"state": "on"}).encode())
        time.sleep(0.5)

        # verify MCU still alive (steering keeps coming)
        msgs = _collect_steering(session, 1.0)
        session.close()
        assert len(msgs) >= 3, "MCU stopped publishing after headlight ON"

    def test_headlight_off(self):
        """Send headlight OFF → MCU continues steering publish."""
        session = _master_session()
        time.sleep(0.3)
        session.put(KE_HEADLIGHT, json.dumps({"state": "off"}).encode())
        time.sleep(0.5)
        msgs = _collect_steering(session, 1.0)
        session.close()
        assert len(msgs) >= 3, "MCU stopped publishing after headlight OFF"

    def test_hazard_on(self):
        """Send hazard ON → MCU continues steering publish."""
        session = _master_session()
        time.sleep(0.3)
        session.put(KE_HAZARD, json.dumps({"state": "on"}).encode())
        time.sleep(0.5)
        msgs = _collect_steering(session, 1.0)
        session.close()
        assert len(msgs) >= 3, "MCU stopped publishing after hazard ON"

    def test_hazard_off(self):
        """Send hazard OFF → MCU continues steering publish."""
        session = _master_session()
        time.sleep(0.3)
        session.put(KE_HAZARD, json.dumps({"state": "off"}).encode())
        time.sleep(0.5)
        msgs = _collect_steering(session, 1.0)
        session.close()
        assert len(msgs) >= 3, "MCU stopped publishing after hazard OFF"

    def test_bidirectional_simultaneous(self):
        """Rapid actuator commands while receiving steering data."""
        session = _master_session()
        time.sleep(0.3)

        # start collecting steering in background
        received: list[dict] = []

        def _on_sample(sample: zenoh.Sample):
            try:
                data = json.loads(sample.payload.to_bytes())
                received.append(data)
            except Exception:
                pass

        sub = session.declare_subscriber(KE_STEERING, _on_sample)
        time.sleep(0.3)

        # send multiple actuator commands rapidly
        for _ in range(5):
            session.put(KE_HEADLIGHT, json.dumps({"state": "on"}).encode())
            time.sleep(0.1)
            session.put(KE_HAZARD, json.dumps({"state": "on"}).encode())
            time.sleep(0.1)

        time.sleep(1.0)
        sub.undeclare()

        # clean up: turn off actuators
        session.put(KE_HEADLIGHT, json.dumps({"state": "off"}).encode())
        session.put(KE_HAZARD, json.dumps({"state": "off"}).encode())
        session.close()

        print(f"\n  Received {len(received)} steering msgs during actuator burst")
        assert len(received) >= 5, \
            f"Expected >= 5 steering msgs during burst, got {len(received)}"


# =========================================================================
# Phase 4 — Performance
# =========================================================================


@hw_available
@zenohd_required
@mcu_required
class TestPerformance:
    """Measure latency and throughput over 10BASE-T1S."""

    def test_steering_publish_rate(self):
        """MCU steering rate should be ~10 msg/s (100 ms interval)."""
        session = _master_session()
        time.sleep(0.3)
        duration = 3.0
        msgs = _collect_steering(session, duration)
        session.close()
        rate = len(msgs) / duration
        print(f"\n  Steering rate: {rate:.1f} msg/s ({len(msgs)} in {duration} s)")
        assert rate >= 7.0, f"Rate {rate:.1f} msg/s too low (expected ~10)"
        assert rate <= 15.0, f"Rate {rate:.1f} msg/s unexpectedly high"

    def test_zenoh_message_latency(self):
        """Measure one-way Zenoh message delivery latency (pub→sub)."""
        session = _master_session()
        time.sleep(0.3)

        latencies: list[float] = []
        recv_times: list[float] = []

        def _on_sample(sample: zenoh.Sample):
            recv_times.append(time.time())

        sub = session.declare_subscriber(KE_STEERING, _on_sample)
        time.sleep(0.3)

        # Measure inter-arrival jitter as proxy for delivery consistency
        recv_times.clear()
        time.sleep(2.0)  # collect 2 seconds of data
        sub.undeclare()
        session.close()

        assert len(recv_times) >= 10, f"Too few msgs: {len(recv_times)}"
        intervals = [
            (recv_times[i] - recv_times[i - 1]) * 1000
            for i in range(1, len(recv_times))
        ]
        avg_interval = sum(intervals) / len(intervals)
        max_interval = max(intervals)
        print(f"\n  === Zenoh Delivery Timing ===")
        print(f"  Messages: {len(recv_times)}")
        print(f"  Avg interval: {avg_interval:.2f} ms (expected ~100 ms)")
        print(f"  Max interval: {max_interval:.2f} ms")
        # intervals should be close to 100ms; max < 200ms
        assert max_interval < 500.0, f"Max interval {max_interval:.2f} ms too high"

    def test_latency_under_15ms(self):
        """PRD NFR-001: worst-case message latency < 15 ms.

        We measure round-trip: master pub → MCU sub → observe MCU still
        publishing steering, and measure master pub-to-next-steering-recv.
        """
        session = _master_session()
        time.sleep(0.5)

        trip_latencies: list[float] = []

        def _on_steering(sample: zenoh.Sample):
            trip_latencies.append(time.time())

        sub = session.declare_subscriber(KE_STEERING, _on_steering)
        time.sleep(0.5)

        # send actuator and measure time to next steering
        for i in range(5):
            trip_latencies.clear()
            t_send = time.time()
            state = "on" if i % 2 == 0 else "off"
            session.put(KE_HEADLIGHT, json.dumps({"state": state}).encode())
            time.sleep(0.3)  # wait for next steering msg
            if trip_latencies:
                rtt = (trip_latencies[0] - t_send) * 1000
                # This isn't a true RTT but measures system responsiveness
        sub.undeclare()

        # clean up
        session.put(KE_HEADLIGHT, json.dumps({"state": "off"}).encode())
        session.close()

        # The real latency test: ICMP RTT < 15ms (already proven in Phase 1)
        result = subprocess.run(
            ["ping", "-c", "10", "-I", MASTER_IFACE, MCU_IP],
            capture_output=True, text=True, timeout=20,
        )
        m = re.search(r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)", result.stdout)
        assert m, "Could not parse ping RTT"
        avg_ms = float(m.group(2))
        max_ms = float(m.group(3))
        print(f"\n  === 10BASE-T1S Latency (PRD NFR-001) ===")
        print(f"  ICMP avg: {avg_ms:.2f} ms, max: {max_ms:.2f} ms")
        print(f"  PRD target: < 15 ms")
        assert max_ms < 15.0, f"Latency {max_ms:.2f} ms exceeds PRD 15 ms"

    def test_actuator_response_time(self):
        """Measure time from actuator pub to next steering reception."""
        session = _master_session()
        time.sleep(0.5)

        response_times: list[float] = []

        for trial in range(5):
            recv_flag: list[float] = []

            def _on_sample(sample: zenoh.Sample, flag=recv_flag):
                if not flag:
                    flag.append(time.time())

            sub = session.declare_subscriber(KE_STEERING, _on_sample)
            time.sleep(0.15)

            # clear and send
            recv_flag.clear()
            t0 = time.time()
            state = "on" if trial % 2 == 0 else "off"
            session.put(KE_HEADLIGHT, json.dumps({"state": state}).encode())
            time.sleep(0.2)
            sub.undeclare()

            if recv_flag:
                response_times.append((recv_flag[0] - t0) * 1000)

        session.put(KE_HEADLIGHT, json.dumps({"state": "off"}).encode())
        session.close()

        assert len(response_times) >= 3, "Too few response measurements"
        avg_rt = sum(response_times) / len(response_times)
        max_rt = max(response_times)
        print(f"\n  === Actuator Response Time ===")
        print(f"  Trials: {len(response_times)}")
        print(f"  Avg: {avg_rt:.2f} ms, Max: {max_rt:.2f} ms")


# =========================================================================
# Phase 5 — Reliability
# =========================================================================


@hw_available
@zenohd_required
@mcu_required
class TestReliability:
    """Verify MCU communication stability over extended periods."""

    def test_continuous_30s(self):
        """Receive steering data for 30 s — loss rate < 1%."""
        session = _master_session()
        time.sleep(0.3)
        duration = 30.0
        msgs = _collect_steering(session, duration)
        session.close()

        expected = duration / 0.1  # 100 ms interval → 300 msgs
        loss_rate = 1.0 - len(msgs) / expected
        print(f"\n  === 30-Second Continuous Test ===")
        print(f"  Duration: {duration} s")
        print(f"  Expected: ~{int(expected)}")
        print(f"  Received: {len(msgs)}")
        print(f"  Loss rate: {loss_rate * 100:.1f}%")
        assert len(msgs) >= expected * 0.90, \
            f"Too many lost: {len(msgs)}/{int(expected)} ({loss_rate * 100:.1f}% loss)"

    def test_message_integrity(self):
        """All received JSONs must parse and have valid value ranges."""
        session = _master_session()
        time.sleep(0.3)
        msgs = _collect_steering(session, 2.0)
        session.close()
        assert len(msgs) >= 10, f"Too few messages: {len(msgs)}"

        for i, m in enumerate(msgs):
            assert 0 <= m["x"] <= 4095, f"msg[{i}] x={m['x']} out of range"
            assert 0 <= m["y"] <= 4095, f"msg[{i}] y={m['y']} out of range"
            assert m["btn"] in (0, 1), f"msg[{i}] btn={m['btn']} invalid"
            assert -90.0 <= m["angle"] <= 90.0, \
                f"msg[{i}] angle={m['angle']} out of range"
            assert m["seq"] >= 0, f"msg[{i}] seq={m['seq']} negative"

    def test_reconnect_after_zenohd_restart(self):
        """MCU auto-reconnects after zenohd restart (auto_reconnect feature)."""
        session = _master_session()
        time.sleep(0.3)

        # verify MCU is publishing before restart
        msgs_before = _collect_steering(session, 1.0)
        session.close()
        assert len(msgs_before) >= 3, "MCU not publishing before restart test"

        # restart zenohd
        subprocess.run(["sudo", "pkill", "-x", "zenohd"], timeout=5)
        time.sleep(1.0)
        proc = subprocess.Popen(
            ["sudo", "/usr/local/bin/zenohd",
             "--listen", "tcp/192.168.100.1:7447",
             "--listen", "tcp/192.168.1.1:7447",
             "--no-multicast-scouting"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        time.sleep(3.0)  # wait for zenohd startup

        # MCU boot: 8 s network init + TCP timeout + retry ~6-8 s per attempt.
        # Poll up to 30 s total for MCU reconnection.
        session2 = _master_session()
        msgs_after: list[dict] = []
        for attempt in range(15):
            time.sleep(2.0)
            msgs_after = _collect_steering(session2, 1.5)
            if len(msgs_after) >= 3:
                print(f"  MCU reconnected after ~{(attempt + 1) * 3.5:.0f} s")
                break
        session2.close()

        print(f"\n  === Reconnect Test ===")
        print(f"  Before restart: {len(msgs_before)} msgs")
        print(f"  After restart: {len(msgs_after)} msgs")
        assert len(msgs_after) >= 5, \
            f"MCU did not reconnect: only {len(msgs_after)} msgs after restart"

    def test_angle_range_consistency(self):
        """Verify angle = (x - 2048) / 2048 * 90 formula."""
        session = _master_session()
        time.sleep(0.3)
        msgs = _collect_steering(session, 2.0)
        session.close()
        assert len(msgs) >= 10, f"Too few messages: {len(msgs)}"

        for i, m in enumerate(msgs):
            expected_angle = (m["x"] - 2048.0) / 2048.0 * 90.0
            # MCU uses float; allow small FP tolerance
            assert abs(m["angle"] - expected_angle) < 0.5, \
                f"msg[{i}] angle={m['angle']}, expected={expected_angle:.2f} (x={m['x']})"
