#!/usr/bin/env python3
"""Vehicle Control Panel — Bidirectional control demo over 10BASE-T1S Zenoh.

RPi (Master) ↔ SAM E70 (Slave):
  Downlink: Headlight/Hazard LED control (publish)
  Uplink:   Thumbstick steering data (subscribe)

Usage:
    python3 -m gui.vehicle_control
    python3 -m gui.vehicle_control --router tcp/192.168.100.1:7447
    python3 -m gui.vehicle_control --sim   # No Zenoh, simulated data
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass, field


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

ZONE = "front_left"
NODE_ID = "1"
KE_HEADLIGHT = f"vehicle/{ZONE}/{NODE_ID}/actuator/headlight"
KE_HAZARD = f"vehicle/{ZONE}/{NODE_ID}/actuator/hazard"
KE_STEERING = f"vehicle/{ZONE}/{NODE_ID}/sensor/steering"

DEFAULT_ROUTER = "tcp/192.168.100.1:7447"


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------

@dataclass
class AppState:
    headlight_on: bool = False
    hazard_on: bool = False
    steering_x: int = 2048
    steering_y: int = 2048
    steering_btn: int = 0
    steering_angle: float = 0.0
    steering_seq: int = 0
    connected: bool = False
    tx_count: int = 0
    rx_count: int = 0
    last_rx_time: float = 0.0
    router_endpoint: str = ""


# --------------------------------------------------------------------------
# Zenoh Bridge (runs in background thread)
# --------------------------------------------------------------------------

class ZenohBridge:
    """Manages Zenoh session for pub/sub, thread-safe updates to AppState."""

    def __init__(self, state: AppState, router: str, sim_mode: bool = False):
        self.state = state
        self.router = router
        self.sim_mode = sim_mode
        self._session = None
        self._sub_steering = None
        self._lock = threading.Lock()
        self._running = False

    def start(self):
        if self.sim_mode:
            self.state.connected = True
            self.state.router_endpoint = "SIM (no Zenoh)"
            self._running = True
            t = threading.Thread(target=self._sim_loop, daemon=True)
            t.start()
            return

        try:
            import zenoh
        except ImportError:
            print("ERROR: eclipse-zenoh not installed. Use --sim for simulation mode.")
            sys.exit(1)

        self.state.router_endpoint = self.router
        t = threading.Thread(target=self._zenoh_thread, daemon=True)
        t.start()

    def _zenoh_thread(self):
        import zenoh
        cfg = zenoh.Config()
        cfg.insert_json5("mode", '"client"')
        cfg.insert_json5("connect/endpoints", f'["{self.router}"]')
        cfg.insert_json5("scouting/multicast/enabled", "false")

        try:
            self._session = zenoh.open(cfg)
            self.state.connected = True
            self._running = True
        except Exception as e:
            print(f"Zenoh connection failed: {e}")
            self.state.connected = False
            return

        self._sub_steering = self._session.declare_subscriber(
            KE_STEERING, self._on_steering
        )

        # Keep thread alive
        while self._running:
            time.sleep(0.5)

    def _on_steering(self, sample):
        try:
            payload = sample.payload.to_string()
            data = json.loads(payload)
            with self._lock:
                self.state.steering_x = int(data.get("x", 2048))
                self.state.steering_y = int(data.get("y", 2048))
                self.state.steering_btn = int(data.get("btn", 0))
                self.state.steering_angle = float(data.get("angle", 0.0))
                self.state.steering_seq = int(data.get("seq", 0))
                self.state.rx_count += 1
                self.state.last_rx_time = time.time()
        except Exception as e:
            print(f"Steering parse error: {e}")

    def publish_headlight(self, on: bool):
        state_str = "on" if on else "off"
        payload = json.dumps({"state": state_str})
        self.state.headlight_on = on
        self.state.tx_count += 1
        if self._session:
            self._session.put(KE_HEADLIGHT, payload)

    def publish_hazard(self, on: bool):
        state_str = "on" if on else "off"
        payload = json.dumps({"state": state_str})
        self.state.hazard_on = on
        self.state.tx_count += 1
        if self._session:
            self._session.put(KE_HAZARD, payload)

    def _sim_loop(self):
        """Generate simulated steering data for testing without hardware."""
        import random
        seq = 0
        while self._running:
            x = 2048 + int(500 * math.sin(seq * 0.05))
            y = 2048 + int(200 * math.cos(seq * 0.03))
            angle = (x - 2048) / 2048.0 * 90.0
            btn = 1 if (seq % 100 < 5) else 0
            with self._lock:
                self.state.steering_x = x
                self.state.steering_y = y
                self.state.steering_btn = btn
                self.state.steering_angle = angle
                self.state.steering_seq = seq
                self.state.rx_count += 1
                self.state.last_rx_time = time.time()
            seq += 1
            time.sleep(0.1)

    def stop(self):
        self._running = False
        if self._sub_steering:
            try:
                self._sub_steering.undeclare()
            except Exception:
                pass
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------

class VehicleControlGUI:
    """Tkinter-based Vehicle Control Panel."""

    BG = "#1a1a2e"
    FG = "#e0e0e0"
    ACCENT = "#0f3460"
    BTN_ON = "#27ae60"
    BTN_OFF = "#555555"
    HAZARD_ON = "#e67e22"
    DANGER = "#e74c3c"
    GAUGE_BG = "#2d2d44"

    def __init__(self, state: AppState, bridge: ZenohBridge):
        self.state = state
        self.bridge = bridge

        self.root = tk.Tk()
        self.root.title("Vehicle Control Panel — 10BASE-T1S Zenoh")
        self.root.configure(bg=self.BG)
        self.root.geometry("720x580")
        self.root.resizable(False, False)

        self._build_ui()
        self._update_loop()

    def _build_ui(self):
        # Title
        title = tk.Label(
            self.root, text="Vehicle Control Panel",
            font=("Helvetica", 18, "bold"), fg="#ffffff", bg=self.BG,
        )
        title.pack(pady=(12, 6))

        # -- Actuators Frame --
        act_frame = tk.LabelFrame(
            self.root, text=" Actuators ",
            font=("Helvetica", 12, "bold"), fg=self.FG, bg=self.BG,
            labelanchor="nw", bd=2, relief="groove",
        )
        act_frame.pack(fill="x", padx=16, pady=6)

        btn_row = tk.Frame(act_frame, bg=self.BG)
        btn_row.pack(pady=12)

        self.btn_headlight = tk.Button(
            btn_row, text="Headlight OFF", width=18, height=2,
            font=("Helvetica", 12, "bold"),
            bg=self.BTN_OFF, fg="#ffffff", activebackground="#666",
            command=self._toggle_headlight, relief="raised", bd=3,
        )
        self.btn_headlight.pack(side="left", padx=20)

        self.btn_hazard = tk.Button(
            btn_row, text="Hazard OFF", width=18, height=2,
            font=("Helvetica", 12, "bold"),
            bg=self.BTN_OFF, fg="#ffffff", activebackground="#666",
            command=self._toggle_hazard, relief="raised", bd=3,
        )
        self.btn_hazard.pack(side="left", padx=20)

        # -- Steering Frame --
        steer_frame = tk.LabelFrame(
            self.root, text=" Steering ",
            font=("Helvetica", 12, "bold"), fg=self.FG, bg=self.BG,
            labelanchor="nw", bd=2, relief="groove",
        )
        steer_frame.pack(fill="x", padx=16, pady=6)

        # Gauge canvas
        self.gauge_canvas = tk.Canvas(
            steer_frame, width=680, height=80,
            bg=self.GAUGE_BG, highlightthickness=0,
        )
        self.gauge_canvas.pack(padx=10, pady=(10, 4))

        # Angle label
        self.lbl_angle = tk.Label(
            steer_frame, text="Angle: 0.0\u00b0",
            font=("Helvetica", 16, "bold"), fg="#00d4ff", bg=self.BG,
        )
        self.lbl_angle.pack(pady=(2, 4))

        # Raw data row
        raw_row = tk.Frame(steer_frame, bg=self.BG)
        raw_row.pack(pady=(0, 10))

        self.lbl_x = tk.Label(
            raw_row, text="X: 2048", font=("Courier", 11),
            fg=self.FG, bg=self.BG, width=12,
        )
        self.lbl_x.pack(side="left", padx=8)

        self.lbl_y = tk.Label(
            raw_row, text="Y: 2048", font=("Courier", 11),
            fg=self.FG, bg=self.BG, width=12,
        )
        self.lbl_y.pack(side="left", padx=8)

        self.lbl_btn = tk.Label(
            raw_row, text="Button: Released", font=("Courier", 11),
            fg=self.FG, bg=self.BG, width=18,
        )
        self.lbl_btn.pack(side="left", padx=8)

        self.lbl_seq = tk.Label(
            raw_row, text="Seq: 0", font=("Courier", 11),
            fg="#888888", bg=self.BG, width=14,
        )
        self.lbl_seq.pack(side="left", padx=8)

        # -- Connection Frame --
        conn_frame = tk.LabelFrame(
            self.root, text=" Connection ",
            font=("Helvetica", 12, "bold"), fg=self.FG, bg=self.BG,
            labelanchor="nw", bd=2, relief="groove",
        )
        conn_frame.pack(fill="x", padx=16, pady=6)

        conn_grid = tk.Frame(conn_frame, bg=self.BG)
        conn_grid.pack(padx=10, pady=8)

        labels = [
            ("Router:", "lbl_router"),
            ("Status:", "lbl_status"),
            ("MCU IP:", "lbl_mcu_ip"),
            ("Messages:", "lbl_msgs"),
        ]
        for i, (text, attr) in enumerate(labels):
            tk.Label(
                conn_grid, text=text, font=("Helvetica", 10, "bold"),
                fg="#aaaaaa", bg=self.BG, anchor="e", width=10,
            ).grid(row=i, column=0, sticky="e", padx=(0, 6), pady=1)
            lbl = tk.Label(
                conn_grid, text="—", font=("Courier", 10),
                fg=self.FG, bg=self.BG, anchor="w",
            )
            lbl.grid(row=i, column=1, sticky="w", pady=1)
            setattr(self, attr, lbl)

    def _toggle_headlight(self):
        new_state = not self.state.headlight_on
        self.bridge.publish_headlight(new_state)
        self._update_headlight_btn()

    def _toggle_hazard(self):
        new_state = not self.state.hazard_on
        self.bridge.publish_hazard(new_state)
        self._update_hazard_btn()

    def _update_headlight_btn(self):
        if self.state.headlight_on:
            self.btn_headlight.configure(
                text="Headlight ON", bg=self.BTN_ON, relief="sunken",
            )
        else:
            self.btn_headlight.configure(
                text="Headlight OFF", bg=self.BTN_OFF, relief="raised",
            )

    def _update_hazard_btn(self):
        if self.state.hazard_on:
            self.btn_hazard.configure(
                text="Hazard ON", bg=self.HAZARD_ON, relief="sunken",
            )
        else:
            self.btn_hazard.configure(
                text="Hazard OFF", bg=self.BTN_OFF, relief="raised",
            )

    def _draw_gauge(self):
        c = self.gauge_canvas
        c.delete("all")
        w, h = 680, 80
        mid_x = w // 2
        mid_y = h // 2

        # Background track
        track_y = mid_y
        c.create_line(30, track_y, w - 30, track_y, fill="#444466", width=4)

        # Center mark
        c.create_line(mid_x, track_y - 15, mid_x, track_y + 15, fill="#666688", width=2)

        # Tick marks every 15 degrees
        for deg in range(-90, 91, 15):
            frac = (deg + 90) / 180.0
            x = 30 + frac * (w - 60)
            tick_h = 10 if deg % 45 == 0 else 5
            c.create_line(x, track_y - tick_h, x, track_y + tick_h, fill="#555577", width=1)
            if deg % 45 == 0:
                c.create_text(x, track_y + 22, text=f"{deg}\u00b0",
                              fill="#888888", font=("Helvetica", 8))

        # Needle position
        angle = max(-90.0, min(90.0, self.state.steering_angle))
        frac = (angle + 90) / 180.0
        needle_x = 30 + frac * (w - 60)

        # Needle color based on magnitude
        mag = abs(angle)
        if mag < 15:
            color = "#00d4ff"
        elif mag < 45:
            color = "#f1c40f"
        else:
            color = "#e74c3c"

        # Draw needle
        c.create_oval(
            needle_x - 8, track_y - 8, needle_x + 8, track_y + 8,
            fill=color, outline="#ffffff", width=2,
        )

        # Direction arrows
        c.create_text(12, track_y, text="\u25c4", fill="#888888", font=("Helvetica", 14))
        c.create_text(w - 12, track_y, text="\u25ba", fill="#888888", font=("Helvetica", 14))

    def _update_loop(self):
        """Periodic UI update (50ms = 20 Hz)."""
        # Steering display
        self._draw_gauge()
        self.lbl_angle.configure(
            text=f"Angle: {self.state.steering_angle:+.1f}\u00b0"
        )
        self.lbl_x.configure(text=f"X: {self.state.steering_x}")
        self.lbl_y.configure(text=f"Y: {self.state.steering_y}")

        btn_text = "Pressed" if self.state.steering_btn else "Released"
        btn_color = self.DANGER if self.state.steering_btn else self.FG
        self.lbl_btn.configure(text=f"Button: {btn_text}", fg=btn_color)
        self.lbl_seq.configure(text=f"Seq: {self.state.steering_seq}")

        # Actuator buttons
        self._update_headlight_btn()
        self._update_hazard_btn()

        # Connection status
        self.lbl_router.configure(text=self.state.router_endpoint or "—")

        if self.state.connected:
            elapsed = time.time() - self.state.last_rx_time if self.state.last_rx_time else 999
            if elapsed < 2.0:
                self.lbl_status.configure(text="Connected (live)", fg=self.BTN_ON)
            elif self.state.rx_count > 0:
                self.lbl_status.configure(text="Connected (stale)", fg="#f1c40f")
            else:
                self.lbl_status.configure(text="Connected (waiting)", fg="#f1c40f")
        else:
            self.lbl_status.configure(text="Disconnected", fg=self.DANGER)

        self.lbl_mcu_ip.configure(text="192.168.100.11")
        self.lbl_msgs.configure(
            text=f"TX {self.state.tx_count} / RX {self.state.rx_count}"
        )

        self.root.after(50, self._update_loop)

    def run(self):
        self.root.mainloop()

    def on_close(self):
        self.bridge.stop()
        self.root.destroy()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Vehicle Control Panel — 10BASE-T1S Zenoh")
    p.add_argument("--router", default=DEFAULT_ROUTER,
                   help=f"Zenoh router endpoint (default: {DEFAULT_ROUTER})")
    p.add_argument("--sim", action="store_true",
                   help="Simulation mode (no Zenoh, generates fake steering data)")
    return p.parse_args()


def main():
    args = parse_args()
    state = AppState()
    bridge = ZenohBridge(state, args.router, sim_mode=args.sim)
    bridge.start()

    gui = VehicleControlGUI(state, bridge)
    gui.root.protocol("WM_DELETE_WINDOW", gui.on_close)
    gui.run()


if __name__ == "__main__":
    main()
