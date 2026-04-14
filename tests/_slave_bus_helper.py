#!/usr/bin/env python3
"""Helper script that runs inside ns_slave network namespace.

Executes slave-side operations (publish/subscribe) through eth2,
ensuring data actually traverses the 10BASE-T1S physical bus.

Usage (run from ns_slave):
  sudo ip netns exec ns_slave python3 tests/_slave_bus_helper.py \
      --action publish_e2e --key vehicle/front/1/sensor/temperature \
      --data '{"value":26.7,"unit":"celsius"}' --count 1

Actions:
  publish_plain   — Publish raw JSON data
  publish_e2e     — Publish E2E-protected data (CRC + seq)
  publish_secoc   — Publish SecOC+E2E protected data (HMAC + CRC)
  publish_corrupt — Publish corrupted E2E data (bad CRC)
  subscribe       — Subscribe and print received messages
"""

import argparse
import json
import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import zenoh

from src.common.e2e_protection import SequenceCounterState
from src.common.payloads import encode, encode_e2e, encode_secoc, ENCODING_JSON


# Ensure user-installed packages are on path (needed when run via sudo)
import site
_user_site = os.path.expanduser("~dama/.local/lib/python3.13/site-packages")
if _user_site not in sys.path:
    sys.path.insert(0, _user_site)

ROUTER_ENDPOINT = "tcp/192.168.1.1:7447"


def _session() -> zenoh.Session:
    conf = zenoh.Config()
    conf.insert_json5("mode", '"client"')
    conf.insert_json5("connect/endpoints", json.dumps([ROUTER_ENDPOINT]))
    return zenoh.open(conf)


def publish_plain(key: str, data: dict, count: int):
    zenoh.init_log_from_env_or("error")
    s = _session()
    time.sleep(0.5)
    for i in range(count):
        payload = data.copy()
        payload["ts"] = time.time() * 1000
        if "value" in payload and count > 1:
            payload["value"] = payload["value"] + i * 0.1
        s.put(key, json.dumps(payload).encode())
        time.sleep(0.15)
    time.sleep(0.5)
    s.close()
    print(json.dumps({"status": "ok", "action": "publish_plain", "count": count}))


def publish_e2e(key: str, data: dict, count: int):
    zenoh.init_log_from_env_or("error")
    s = _session()
    time.sleep(0.5)
    counter = SequenceCounterState()
    for i in range(count):
        payload = data.copy()
        payload["ts"] = time.time() * 1000
        if "value" in payload and count > 1:
            payload["value"] = payload["value"] + i * 0.1
        encoded = encode_e2e(payload, key, counter)
        s.put(key, encoded)
        time.sleep(0.15)
    time.sleep(0.5)
    s.close()
    print(json.dumps({"status": "ok", "action": "publish_e2e", "count": count}))


def publish_secoc(key: str, data: dict, count: int, hmac_key_hex: str):
    zenoh.init_log_from_env_or("error")
    hmac_key = bytes.fromhex(hmac_key_hex)
    s = _session()
    time.sleep(0.5)
    counter = SequenceCounterState()
    for i in range(count):
        payload = data.copy()
        payload["ts"] = time.time() * 1000
        if "value" in payload and count > 1:
            payload["value"] = payload["value"] + i * 0.1
        encoded = encode_secoc(payload, key, counter, hmac_key)
        s.put(key, encoded)
        time.sleep(0.15)
    time.sleep(0.5)
    s.close()
    print(json.dumps({"status": "ok", "action": "publish_secoc", "count": count}))


def publish_corrupt(key: str, data: dict, count: int):
    zenoh.init_log_from_env_or("error")
    s = _session()
    time.sleep(0.5)
    counter = SequenceCounterState()
    for i in range(count):
        payload = data.copy()
        payload["ts"] = time.time() * 1000
        encoded = encode_e2e(payload, key, counter)
        corrupted = bytearray(encoded)
        corrupted[-1] ^= 0xFF
        s.put(key, bytes(corrupted))
        time.sleep(0.15)
    time.sleep(0.5)
    s.close()
    print(json.dumps({"status": "ok", "action": "publish_corrupt", "count": count}))


def subscribe_and_collect(key: str, count: int, timeout: float):
    zenoh.init_log_from_env_or("error")
    s = _session()
    time.sleep(0.5)
    received = []

    def on_sample(sample: zenoh.Sample):
        received.append(sample.payload.to_bytes().hex())

    s.declare_subscriber(key, on_sample)
    deadline = time.time() + timeout
    while len(received) < count and time.time() < deadline:
        time.sleep(0.1)
    s.close()
    print(json.dumps({"status": "ok", "action": "subscribe", "received": received}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True,
                        choices=["publish_plain", "publish_e2e", "publish_secoc",
                                 "publish_corrupt", "subscribe"])
    parser.add_argument("--key", required=True)
    parser.add_argument("--data", default='{"value":25.0,"unit":"celsius"}')
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--hmac-key", default="")
    args = parser.parse_args()

    data = json.loads(args.data)

    if args.action == "publish_plain":
        publish_plain(args.key, data, args.count)
    elif args.action == "publish_e2e":
        publish_e2e(args.key, data, args.count)
    elif args.action == "publish_secoc":
        publish_secoc(args.key, data, args.count, args.hmac_key)
    elif args.action == "publish_corrupt":
        publish_corrupt(args.key, data, args.count)
    elif args.action == "subscribe":
        subscribe_and_collect(args.key, args.count, args.timeout)
