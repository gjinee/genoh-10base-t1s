"""Master GUI — FastAPI application for the PLCA Coordinator / Zenoh Router."""

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
from gui.common.sim_engine import SafetyState, get_engine
from gui.common.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine()
    engine.set_managers(master=manager)
    yield


app = FastAPI(title="10BASE-T1S Master Controller", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html = (HERE / "templates" / "master.html").read_text()
    return HTMLResponse(html)


@app.get("/api/state")
async def get_state() -> dict:
    return get_engine().get_full_state()


@app.get("/api/scenarios")
async def list_scenarios() -> list[str]:
    return get_engine().list_scenarios()


@app.post("/api/scenario/{name}")
async def load_scenario(name: str) -> dict:
    engine = get_engine()
    result = engine.load_scenario(name)
    await manager.broadcast(WSMessage(
        type=MsgType.SCENARIO_LOAD,
        source="master",
        payload={"name": name, "data": result},
    ))
    return result


@app.post("/api/start")
async def start_sim() -> dict:
    engine = get_engine()
    if not engine.running:
        asyncio.create_task(engine.run_loop())
    return {"status": "running"}


@app.post("/api/stop")
async def stop_sim() -> dict:
    get_engine().stop()
    return {"status": "stopped"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    engine = get_engine()
    # Send initial state
    await manager.send_personal(ws, WSMessage(
        type=MsgType.INIT_STATE,
        source="master",
        payload=engine.get_full_state(),
    ))
    try:
        while True:
            raw = await ws.receive_text()
            msg = WSMessage.from_json(raw)
            await _handle_master_command(msg)
    except WebSocketDisconnect:
        await manager.disconnect(ws)


async def _handle_master_command(msg: WSMessage) -> None:
    engine = get_engine()

    if msg.type == MsgType.CMD_MANUAL_ACTUATOR:
        p = msg.payload
        cmd = engine.encode_actuator_command(
            p["node_id"], p["actuator_type"], p["action"], p.get("params", {}),
        )
        # Update node actuator state
        node = engine.nodes.get(p["node_id"])
        if node and p["actuator_type"] in node.actuators:
            node.actuators[p["actuator_type"]] = {"state": p["action"], **p.get("params", {})}
            node.rx_count += 1
            node.secoc_ok += 1
        # HW mode: publish actuator command to real Zenoh bus
        if engine.mode == "hw" and engine._zenoh_session and node:
            import json as _json
            key_expr = f"vehicle/{node.zone}/{p['node_id']}/actuator/{p['actuator_type']}"
            payload = _json.dumps({
                "action": p["action"], "params": p.get("params", {}),
                "mac": cmd.get("mac", ""), "ts": int(time.time() * 1000),
            }).encode()
            engine._zenoh_put(key_expr, payload)
        await manager.broadcast(WSMessage(
            type=MsgType.ACTUATOR_CMD, source="master", payload=cmd,
        ))
        # Forward to slave manager too
        if engine._slave_mgr:
            await engine._slave_mgr.broadcast(WSMessage(
                type=MsgType.ACTUATOR_CMD, source="master", payload=cmd,
            ))

    elif msg.type == MsgType.CMD_INJECT_FAULT:
        p = msg.payload
        result = engine.report_fault(p["fault_type"], p.get("node_id", ""))
        await manager.broadcast(WSMessage(
            type=MsgType.SAFETY_STATE, source="master", payload=result,
        ))

    elif msg.type == MsgType.CMD_RESET_SAFETY:
        result = engine.transition_safety(SafetyState.NORMAL, "Manual reset")
        await manager.broadcast(WSMessage(
            type=MsgType.SAFETY_STATE, source="master", payload=result,
        ))

    elif msg.type == MsgType.CMD_KICK_WATCHDOG:
        engine.kick_watchdog()

    elif msg.type == MsgType.PING:
        await manager.broadcast(WSMessage(type=MsgType.PONG, source="master"))


def run(host: str = "0.0.0.0", port: int = 8010, mode: str = "sim") -> None:
    import uvicorn
    get_engine(mode)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
