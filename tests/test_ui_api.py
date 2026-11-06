from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import numpy as np
import pytest
import soundfile as sf
import yaml
from fastapi.testclient import TestClient

from sonify.bus import EventBus
from sonify.config import load_config, parse_config, save_config
from sonify.daemon import Daemon
from sonify.engine import Engine, SoundBank
from sonify.mapper import Mapper
from sonify.ui.server import create_app

from fakes import FakeBackend

BASE = "http://127.0.0.1:8765"

RAW: Dict[str, Any] = {
    "sounds": {
        "bell": {"key": "b", "cooldown_s": 0},
        "harp": {"key": "h", "kind": "pitched"},
    },
    "signals": {
        "mem": {"events": [{"sound": "bell", "when": {"above": 85}, "cooldown_s": 30}]},
    },
}


@pytest.fixture
def ctx(tmp_path: Path):
    sounds = tmp_path / "sounds"
    for sid in ("bell", "harp"):
        (sounds / sid).mkdir(parents=True)
        tone = np.zeros(2205, dtype=np.float32)
        sf.write(str(sounds / sid / "1.wav"), np.stack([tone, tone], axis=1), 44100, subtype="PCM_16")
    config_path = tmp_path / "config.yaml"
    config = parse_config(RAW)
    save_config(config, config_path)
    bus = EventBus()
    backend = FakeBackend()
    engine = Engine(config, SoundBank(sounds), backend, bus)
    daemon = Daemon(config, engine, Mapper(config, bus), bus, sources=[])
    client = TestClient(create_app(daemon, config_path), base_url=BASE)
    return client, daemon, config_path, backend, bus


def test_get_config_round_trips(ctx) -> None:
    client, *_ = ctx
    body = client.get("/config").json()
    assert body["signals"]["mem"]["events"][0]["when"]["above"] == 85
    assert parse_config(body)  # what GET returns is itself valid input for PUT


def test_put_config_rejects_invalid_with_paths_and_does_not_write(ctx) -> None:
    client, daemon, config_path, *_ = ctx
    before = config_path.read_text()
    bad = client.get("/config").json()
    bad["master_volume"] = 3
    bad["signals"]["mem"]["events"][0]["cooldown_s"] = -1
    response = client.put("/config", json=bad)
    assert response.status_code == 422
    paths = {e["path"] for e in response.json()["errors"]}
    assert {"master_volume", "signals.mem.events.0.cooldown_s"} <= paths
    assert config_path.read_text() == before
    assert daemon.config.master_volume != 3


def test_put_config_rejects_unknown_keys_and_non_mapping(ctx) -> None:
    client, *_ = ctx
    assert client.put("/config", json={"nonsense": 1}).status_code == 422
    assert client.put("/config", json=[1, 2]).status_code == 422


def test_put_config_saves_atomically_and_hot_reloads(ctx) -> None:
    client, daemon, config_path, _, bus = ctx
    seen = []
    bus.subscribe(seen.append)
    new = client.get("/config").json()
    new["signals"]["mem"]["events"][0]["when"]["above"] = 70
    response = client.put("/config", json=new)
    assert response.status_code == 200 and response.json()["ok"] is True
    assert load_config(config_path).signals["mem"].events[0].when.above == 70
    assert daemon.config.signals["mem"].events[0].when.above == 70
    assert not list(config_path.parent.glob(".config.yaml.*"))  # temp file renamed away
    assert any(e.type == "config" for e in seen)


def test_put_config_warns_about_missing_sounds(ctx) -> None:
    client, *_ = ctx
    new = client.get("/config").json()
    new["sounds"]["ghost"] = {"key": "g"}
    new["signals"]["mem"]["events"][0]["sound"] = "ghost"
    warnings = client.put("/config", json=new).json()["warnings"]
    assert warnings and "ghost" in warnings[0]


def test_preview_mute_volume_mixer_solo(ctx) -> None:
    client, daemon, _, backend, _ = ctx
    assert client.post("/preview/bell").json() == {"played": True, "suppressed": None}
    assert len(backend.channels) == 1
    assert client.post("/preview/harp", json={"pitch": 3}).json()["played"] is True
    assert client.post("/preview/nope").status_code == 404

    assert client.post("/mute").json() == {"muted": True}
    assert client.post("/preview/bell").json()["suppressed"] == "muted"
    assert client.post("/mute", json={"muted": False}).json() == {"muted": False}

    assert client.put("/volume", json={"volume": 0.25}).json() == {"volume": 0.25}
    assert daemon.engine.master_volume == 0.25
    assert client.put("/volume", json={"volume": 2}).status_code == 422

    state = client.put("/mixer/bell", json={"volume": 0.4, "muted": True, "cooldown_s": 2}).json()
    assert state == {"volume": 0.4, "muted": True, "cooldown_s": 2.0, "kind": "oneshot"}
    assert client.put("/mixer/nope", json={"volume": 0.4}).status_code == 404

    assert client.put("/solo", json={"sound": "harp"}).json() == {"solo": "harp"}
    assert daemon.engine.state()["solo"] == "harp"


def test_websocket_sends_snapshot_then_streams_bus_events(ctx) -> None:
    client, daemon, _, _, bus = ctx
    with client.websocket_connect("/ws", headers={"host": "127.0.0.1:8765"}) as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot" and snapshot["v"] == 1
        assert {"metrics", "history", "state", "mappings", "sounds", "revision"} <= set(snapshot["data"])
        daemon.mapper.update(__import__("sonify.models", fromlist=["Sample"]).Sample("mem", 91.0, "%"))
        message = ws.receive_json()
        assert message["type"] == "metric" and message["data"]["value"] == 91.0


def test_requests_from_other_hosts_or_origins_are_refused(ctx) -> None:
    client, *_ = ctx
    assert client.get("/config", headers={"host": "evil.example:8765"}).status_code == 403
    assert client.post("/mute", headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post("/mute", headers={"origin": BASE}).status_code == 200
