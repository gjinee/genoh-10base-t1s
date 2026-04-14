"""Slave GUI — FastAPI application for individual slave node simulation."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from gui.common.protocol import MsgType, WSMessage
from gui.common.sim_engine import get_engine
from gui.common.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine()
    engine.set_managers(slave=manager)
    yield


app = FastAPI(title="10BASE-T1S Slave Node", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html = (HERE / "templates" / "slave.html").read_text()
    return HTMLResponse(html)


@app.get("/api/state")
async def get_state() -> dict:
    return get_engine().get_full_state()


@app.post("/api/register")
async def register_node(node_id: str, zone: str = "front_left", plca_id: int = 1, role: str = "sensor") -> dict:
    engine = get_engine()
    node = engine.register_node(node_id, zone, plca_id, role)
    await manager.broadcast(WSMessage(
        type=MsgType.NODE_REGISTER,
        source="slave",
        payload={
            "node_id": node_id, "zone": zone,
            "plca_id": plca_id, "role": role,
        },
    ))
    # Also notify master
    if engine._master_mgr:
        await engine._master_mgr.broadcast(WSMessage(
            type=MsgType.NODE_REGISTER,
            source="slave",
            payload={
                "node_id": node_id, "zone": zone,
                "plca_id": plca_id, "role": role,
            },
        ))
    return {"status": "registered", "node_id": node_id}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    engine = get_engine()
    await manager.send_personal(ws, WSMessage(
        type=MsgType.INIT_STATE,
        source="slave",
        payload=engine.get_full_state(),
    ))
    try:
        while True:
            raw = await ws.receive_text()
            msg = WSMessage.from_json(raw)
            await _handle_slave_command(msg)
    except WebSocketDisconnect:
        await manager.disconnect(ws)


async def _handle_slave_command(msg: WSMessage) -> None:
    engine = get_engine()

    if msg.type == MsgType.SENSOR_DATA:
        # Manual sensor value from slave GUI
        p = msg.payload
        node = engine.nodes.get(p["node_id"])
        if node:
            node.sensors[p["sensor_type"]] = p["value"]
            encoded = engine.encode_sensor_message(p["node_id"], p["sensor_type"], p["value"])
            # HW mode: publish to real Zenoh → 10BASE-T1S bus
            if engine.mode == "hw" and engine._zenoh_session:
                from gui.common.sim_engine import e2e_encode
                key_expr = f"vehicle/{node.zone}/{p['node_id']}/sensor/{p['sensor_type']}"
                payload_json = json.dumps({
                    "value": p["value"],
                    "unit": encoded.get("unit", ""),
                    "ts": int(time.time() * 1000),
                }).encode()
                e2e_bytes = e2e_encode(payload_json, 0x1001, node.seq_counter)
                engine._zenoh_put(key_expr, e2e_bytes)
            await manager.broadcast(WSMessage(
                type=MsgType.SENSOR_DATA, source="slave", payload=encoded,
            ))
            if engine._master_mgr:
                await engine._master_mgr.broadcast(WSMessage(
                    type=MsgType.SENSOR_DATA, source="slave", payload=encoded,
                ))

    elif msg.type == MsgType.CMD_ATTACK:
        p = msg.payload
        attack = p.get("attack_type", "spoof")
        node_id = p.get("node_id", "attacker")
        if attack == "spoof":
            alert = engine.ids_check(
                "IDS-001", node_id, "Spoofed message with wrong HMAC key", "HIGH",
            )
        elif attack == "replay":
            alert = engine.ids_check(
                "IDS-004", node_id, "Replay of previously valid message", "HIGH",
            )
        elif attack == "flood":
            alert = engine.ids_check(
                "IDS-002", node_id, "Message rate exceeded (flooding)", "CRITICAL",
            )
        elif attack == "unauthorized":
            alert = engine.ids_check(
                "IDS-001", node_id, "Unauthorized key expression publish", "MEDIUM",
            )
        else:
            return

        alert_payload = {
            "rule_id": alert.rule_id,
            "severity": alert.severity,
            "source_node": alert.source_node,
            "description": alert.description,
            "ts": alert.ts,
        }
        await manager.broadcast(WSMessage(
            type=MsgType.IDS_ALERT, source="slave", payload=alert_payload,
        ))
        if engine._master_mgr:
            await engine._master_mgr.broadcast(WSMessage(
                type=MsgType.IDS_ALERT, source="engine", payload=alert_payload,
            ))

    elif msg.type == MsgType.CMD_INJECT_FAULT:
        p = msg.payload
        node_id = p.get("node_id", "")
        if p.get("fault_type") == "NODE_OFFLINE" and node_id:
            node = engine.nodes.get(node_id)
            if node:
                node.alive = False
            result = engine.report_fault("NODE_OFFLINE", node_id)
            await manager.broadcast(WSMessage(
                type=MsgType.NODE_OFFLINE, source="slave",
                payload={"node_id": node_id},
            ))
            if engine._master_mgr:
                await engine._master_mgr.broadcast(WSMessage(
                    type=MsgType.SAFETY_STATE, source="engine", payload=result,
                ))

    elif msg.type == MsgType.NODE_REGISTER:
        p = msg.payload
        engine.register_node(p["node_id"], p["zone"], p["plca_id"], p["role"])
        if engine._master_mgr:
            await engine._master_mgr.broadcast(WSMessage(
                type=MsgType.NODE_REGISTER, source="slave", payload=p,
            ))

    elif msg.type == MsgType.PING:
        await manager.broadcast(WSMessage(type=MsgType.PONG, source="slave"))


def run(host: str = "0.0.0.0", port: int = 8020, mode: str = "sim") -> None:
    import uvicorn
    get_engine(mode)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
