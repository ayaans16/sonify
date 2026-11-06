from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict

import numpy as np
import pytest
import soundfile as sf


@pytest.fixture
def fake_minecraft(tmp_path: Path) -> Path:
    """A minimal assets dir: one index, sounds.json and two real OGG files."""
    assets = tmp_path / "assets"
    (assets / "indexes").mkdir(parents=True)
    objects: Dict[str, dict] = {}

    def add(logical: str, payload: bytes) -> None:
        digest = hashlib.sha1(payload).hexdigest()
        path = assets / "objects" / digest[:2] / digest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        objects[logical] = {"hash": digest, "size": len(payload)}

    def ogg(freq: float, rate: int = 22050) -> bytes:
        t = np.arange(rate // 4) / rate
        tone = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
        out = assets.parent / f"tmp_{freq}.ogg"
        sf.write(str(out), tone, rate, format="OGG", subtype="VORBIS")
        return out.read_bytes()

    add("minecraft/sounds/mob/creeper/say1.ogg", ogg(220))
    add("minecraft/sounds/mob/creeper/say2.ogg", ogg(330))
    add("minecraft/sounds/note/harp.ogg", ogg(440))
    sounds_json = {
        "entity.creeper.primed": {"sounds": ["mob/creeper/say1", {"name": "minecraft:mob/creeper/say2"}]},
        "block.note_block.harp": {"sounds": [{"name": "note/harp"}]},
        "alias.event": {"sounds": [{"name": "entity.creeper.primed", "type": "event"}]},
    }
    add("minecraft/sounds.json", json.dumps(sounds_json).encode())
    (assets / "indexes" / "17.json").write_text(json.dumps({"objects": objects}))
    return assets
