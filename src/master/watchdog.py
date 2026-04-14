"""Software watchdog timer with systemd sd_notify integration.

Implements a configurable watchdog that monitors the master application
main loop. If the watchdog is not kicked within the timeout period,
the expiry callback fires to notify the safety state machine.
See functional_safety.md Section 4.2.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = 5.0


def _try_sd_notify(state: str) -> bool:
    """Send sd_notify message to systemd, if available.

    Args:
        state: systemd notify state string (e.g., "WATCHDOG=1")

    Returns:
        True if notification was sent successfully.
    """
    notify_socket = os.environ.get("NOTIFY_SOCKET")
    if not notify_socket:
        return False
    try:
        import socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            if notify_socket.startswith("@"):
                notify_socket = "\0" + notify_socket[1:]
            sock.sendto(state.encode("utf-8"), notify_socket)
            return True
        finally:
            sock.close()
    except (OSError, ImportError) as e:
        logger.debug("sd_notify failed: %s", e)
        return False


class Watchdog:
    """Software watchdog timer with optional systemd integration.

    The application main loop must call kick() regularly. If kick()
    is not called within timeout_sec, the expiry_callback fires.

    Usage:
        def on_watchdog_expired():
            safety_manager.notify_fault(FaultType.WATCHDOG_EXPIRED, ...)

        wd = Watchdog(timeout_sec=5.0, expiry_callback=on_watchdog_expired)
        wd.start()

        # In main loop:
        while running:
            process_sensors()
            process_actuators()
            wd.kick()

        wd.stop()
    """

    def __init__(
        self,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        expiry_callback: Callable[[], None] | None = None,
    ):
        self._timeout_sec = timeout_sec
        self._expiry_callback = expiry_callback
        self._last_kick: float = 0.0
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    @property
    def timeout_sec(self) -> float:
        return self._timeout_sec

    @property
    def is_running(self) -> bool:
        return self._running

    def kick(self) -> None:
        """Reset the watchdog timer. Must be called periodically.

        Also sends WATCHDOG=1 to systemd if NOTIFY_SOCKET is set.
        """
        with self._lock:
            self._last_kick = time.monotonic()
        _try_sd_notify("WATCHDOG=1")

    def start(self) -> None:
        """Start the watchdog monitoring thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._last_kick = time.monotonic()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="watchdog",
            daemon=True,
        )
        self._thread.start()
        _try_sd_notify("READY=1")
        logger.info("Watchdog started (timeout=%.1fs)", self._timeout_sec)

    def stop(self) -> None:
        """Stop the watchdog monitoring thread."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._timeout_sec + 1)
        self._thread = None
        logger.info("Watchdog stopped")

    def _monitor_loop(self) -> None:
        """Background thread that checks for watchdog expiry."""
        check_interval = min(self._timeout_sec / 4, 1.0)
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=check_interval)
            if self._stop_event.is_set():
                break
            with self._lock:
                elapsed = time.monotonic() - self._last_kick
            if elapsed > self._timeout_sec:
                logger.error(
                    "Watchdog expired! No kick for %.1fs (timeout=%.1fs)",
                    elapsed,
                    self._timeout_sec,
                )
                if self._expiry_callback:
                    try:
                        self._expiry_callback()
                    except Exception:
                        logger.exception("Watchdog expiry callback failed")
                # Reset to avoid repeated expiry callbacks
                with self._lock:
                    self._last_kick = time.monotonic()
