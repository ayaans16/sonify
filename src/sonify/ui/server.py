"""FastAPI dashboard: a read-only subscriber on the bus plus a few controls.

The UI never duplicates daemon logic. It subscribes to the event bus for
everything it displays and calls the engine's / daemon's public methods for
everything it changes. It binds to 127.0.0.1 only and makes no outbound
requests.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import uvicorn
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..bus import SCHEMA_VERSION, Event
from ..config import parse_config, save_config, validate_mapping
from ..daemon import Daemon
from ..mapper import referenced_sounds, root_pitch
from ..models import SoundEvent
from .tracker import StateTracker

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
HOST = "127.0.0.1"
DEFAULT_PORT = 8765
WS_QUEUE_SIZE = 500


class VolumeBody(BaseModel):
    volume: float = Field(ge=0, le=1)


class MuteBody(BaseModel):
    muted: Optional[bool] = None  # omitted -> toggle


class MixerBody(BaseModel):
    volume: Optional[float] = Field(None, ge=0, le=1)
    muted: Optional[bool] = None
    cooldown_s: Optional[float] = Field(None, ge=0, le=3600)


class SoloBody(BaseModel):
    sound: Optional[str] = None


class PreviewBody(BaseModel):
    pitch: Optional[int] = None


class LocalOnlyMiddleware:
    """Reject requests whose Host/Origin is not this server on loopback.

    Binding to 127.0.0.1 keeps other machines out; this additionally stops a
    web page in the user's browser from driving the dashboard (CSRF, DNS
    rebinding, cross-site WebSockets).
    """

    def __init__(self, app: Any, port: int) -> None:
        self.app = app
        self.allowed = {f"{h}:{port}" for h in ("127.0.0.1", "localhost", "[::1]")}

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
            origin = headers.get("origin")
            origin_ok = origin is None or urlparse(origin).netloc in self.allowed
            if headers.get("host") not in self.allowed or not origin_ok:
                if scope["type"] == "http":
                    await PlainTextResponse("forbidden", status_code=403)(scope, receive, send)
                else:
                    await receive()
                    await send({"type": "websocket.close", "code": 1008})
                return
        await self.app(scope, receive, send)


def create_app(daemon: Daemon, config_path: Path, port: int = DEFAULT_PORT) -> FastAPI:
    app = FastAPI(title="sonify", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(LocalOnlyMiddleware, port=port)
    engine, bus = daemon.engine, daemon.bus
    tracker = StateTracker(bus)
    config_lock = threading.Lock()

    def sounds_listing() -> List[Dict[str, Any]]:
        have = set(engine.bank.available())
        return [
            {"id": sid, "kind": sdef.kind, "key": sdef.key, "installed": sid in have}
            for sid, sdef in daemon.config.sounds.items()
        ]

    def snapshot() -> Dict[str, Any]:
        return {
            **tracker.snapshot(),
            "state": engine.state(),
            "mappings": daemon.mapper.describe(),
            "sounds": sounds_listing(),
            "revision": daemon.revision,
        }

    def known_sound(sound: str) -> None:
        if sound not in daemon.config.sounds:
            raise HTTPException(404, f"unknown sound '{sound}'")

    # ------------------------------------------------------------ websocket

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        await socket.accept()
        loop = asyncio.get_running_loop()
        queue: "asyncio.Queue[Event]" = asyncio.Queue(maxsize=WS_QUEUE_SIZE)

        def offer(event: Event) -> None:  # called from any thread
            def put() -> None:
                if not queue.full():
                    queue.put_nowait(event)

            loop.call_soon_threadsafe(put)

        # Subscribe first, then snapshot, so no event falls in the gap.
        unsubscribe = bus.subscribe(offer)
        try:
            await socket.send_json(
                {"v": SCHEMA_VERSION, "type": "snapshot", "ts": time.time(), "data": snapshot()}
            )
            while True:
                await socket.send_json((await queue.get()).to_dict())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            unsubscribe()

    # ----------------------------------------------------------------- REST

    @app.get("/config")
    def get_config() -> Dict[str, Any]:
        return daemon.config.to_plain()

    @app.put("/config")
    def put_config(raw: Any = Body(...)) -> JSONResponse:
        errors = validate_mapping(raw)
        if errors:
            return JSONResponse({"errors": [e.to_dict() for e in errors]}, status_code=422)
        config = parse_config(raw)
        with config_lock:
            save_config(config, config_path)
            daemon.apply_config(config)
        missing = engine.bank.missing(referenced_sounds(config))
        warnings = [f"no sound files for '{m}' (run `sonify setup`)" for m in missing]
        return JSONResponse({"ok": True, "revision": daemon.revision, "warnings": warnings})

    @app.get("/sounds")
    def get_sounds() -> List[Dict[str, Any]]:
        return sounds_listing()

    @app.post("/preview/{sound}")
    def preview(sound: str, body: Optional[PreviewBody] = None) -> Dict[str, Any]:
        known_sound(sound)
        pitch = body.pitch if body else None
        if pitch is None and daemon.config.sounds[sound].kind == "pitched":
            pitch = root_pitch(daemon.config)
        reason = engine.play(
            SoundEvent(sound=sound, signal="preview", value=0.0, rule="preview", pitch=pitch),
            force=True,
        )
        return {"played": reason is None, "suppressed": reason}

    @app.post("/mute")
    def mute(body: Optional[MuteBody] = None) -> Dict[str, bool]:
        muted = body.muted if body and body.muted is not None else not engine.muted
        engine.set_muted(muted)
        return {"muted": muted}

    @app.put("/volume")
    def volume(body: VolumeBody) -> Dict[str, float]:
        engine.set_master_volume(body.volume)
        return {"volume": body.volume}

    @app.put("/mixer/{sound}")
    def mixer(sound: str, body: MixerBody) -> Dict[str, Any]:
        known_sound(sound)
        if body.volume is not None:
            engine.set_sound_volume(sound, body.volume)
        if body.muted is not None:
            engine.set_sound_muted(sound, body.muted)
        if body.cooldown_s is not None:
            engine.set_cooldown(sound, body.cooldown_s)
        return engine.state()["per_sound"][sound]

    @app.put("/solo")
    def solo(body: SoloBody) -> Dict[str, Optional[str]]:
        if body.sound is not None:
            known_sound(body.sound)
        engine.set_solo(body.sound)
        return {"solo": body.sound}

    # --------------------------------------------------------------- static

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


class DashboardServer:
    """Runs uvicorn on a background thread, bound to loopback only."""

    def __init__(self, app: FastAPI, port: int = DEFAULT_PORT) -> None:
        self.port = port
        self.url = f"http://localhost:{port}"
        self._server = uvicorn.Server(
            uvicorn.Config(app, host=HOST, port=port, log_level="warning", ws="auto")
        )
        self._thread = threading.Thread(target=self._server.run, name="dashboard", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=3)
