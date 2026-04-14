"""10BASE-T1S bus monitor — reads real or simulated traffic for GUI display.

In HW mode, bridges actual Zenoh session events to the GUI WebSocket.
In SIM mode, uses the in-memory message store from sim_engine.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from gui.common.protocol import MsgType, WSMessage
from gui.common.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)


class BusMonitor:
    """Monitors Zenoh bus traffic and pushes events to GUI connections."""

    def __init__(self, mode: str = "sim") -> None:
        self.mode = mode
        self.running = False
        self.message_count = 0
        self.bytes_total = 0
        self.start_time = time.time()

    @property
    def throughput_msg_s(self) -> float:
        elapsed = time.time() - self.start_time
        return self.message_count / max(elapsed, 0.001)

    @property
    def throughput_bytes_s(self) -> float:
        elapsed = time.time() - self.start_time
        return self.bytes_total / max(elapsed, 0.001)

    def record_message(self, key_expr: str, payload_size: int) -> None:
        self.message_count += 1
        self.bytes_total += payload_size

    async def run_hw_monitor(self, manager: ConnectionManager) -> None:
        """In HW mode, subscribe to real Zenoh session and forward to GUI.

        Requires zenohd running and eclipse-zenoh installed.
        """
        if self.mode != "hw":
            return

        try:
            import zenoh
        except ImportError:
            logger.warning("eclipse-zenoh not available, HW monitor disabled")
            return

        self.running = True
        config = zenoh.Config()
        session = zenoh.open(config)

        def on_sample(sample):
            self.record_message(str(sample.key_expr), len(sample.payload))

        sub = session.declare_subscriber("vehicle/**", on_sample)
        logger.info("HW bus monitor started on vehicle/**")

        try:
            while self.running:
                await asyncio.sleep(1.0)
        finally:
            sub.undeclare()
            session.close()

    def stop(self) -> None:
        self.running = False
