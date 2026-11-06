from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np
import pytest
import soundfile as sf

from sonify.bus import Event, EventBus
from sonify.config import parse_config
from sonify.engine import Engine, SoundBank
from sonify.engine.ducking import Ducker
from sonify.models import AmbientUpdate, SoundEvent

from fakes import FakeBackend


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def sounds_dir(tmp_path: Path) -> Path:
    for sid in ("hiss", "harp", "bed"):
        folder = tmp_path / sid
        folder.mkdir()
        tone = (np.sin(np.linspace(0, 200, 4410)) * 0.3).astype(np.float32)
        sf.write(str(folder / "1.wav"), np.stack([tone, tone], axis=1), 44100, subtype="PCM_16")
    return tmp_path


def make_engine(sounds_dir: Path, **overrides):
    raw = {
        "polyphony": 2,
        "max_events_per_s": 100,
        "sounds": {
            "hiss": {"key": "x", "cooldown_s": 1.0},
            "harp": {"key": "y", "kind": "pitched", "cooldown_s": 0.0},
            "bed": {"key": "z", "kind": "loop", "volume": 0.5},
        },
        "ducking": {"enabled": False},
    }
    raw.update(overrides)
    backend, clock, bus = FakeBackend(), Clock(), EventBus()
    seen: List[Event] = []
    bus.subscribe(seen.append)
    engine = Engine(parse_config(raw), SoundBank(sounds_dir), backend, bus, clock)
    return engine, backend, clock, seen


def ev(sound: str = "hiss", **kw) -> SoundEvent:
    return SoundEvent(sound=sound, signal="s", value=1.0, **kw)


def test_plays_and_publishes_sound_event(sounds_dir: Path) -> None:
    engine, backend, _, seen = make_engine(sounds_dir)
    assert engine.play(ev()) is None
    assert len(backend.channels) == 1
    sound_events = [e for e in seen if e.type == "sound"]
    assert sound_events[0].data["sound"] == "hiss"
    assert sound_events[0].data["suppressed"] is None


def test_per_sound_cooldown(sounds_dir: Path) -> None:
    engine, backend, clock, _ = make_engine(sounds_dir)
    assert engine.play(ev()) is None
    clock.now += 0.5
    assert engine.play(ev()) == "cooldown"
    clock.now += 0.6
    assert engine.play(ev()) is None
    assert len(backend.channels) == 2


def test_runtime_cooldown_override(sounds_dir: Path) -> None:
    engine, _, clock, _ = make_engine(sounds_dir)
    engine.set_cooldown("hiss", 10)
    engine.play(ev())
    clock.now += 5
    assert engine.play(ev()) == "cooldown"


def test_global_rate_limit(sounds_dir: Path) -> None:
    engine, _, _, _ = make_engine(sounds_dir, max_events_per_s=2, polyphony=10)
    results = [engine.play(ev("harp")) for _ in range(4)]
    assert results == [None, None, "rate_limit", "rate_limit"]


def test_polyphony_steals_oldest_voice(sounds_dir: Path) -> None:
    engine, backend, clock, _ = make_engine(sounds_dir)
    for _ in range(3):
        engine.play(ev("harp"))
        clock.now += 0.01
    assert not backend.channels[0].busy  # oldest was stopped
    assert backend.channels[1].busy and backend.channels[2].busy


def test_mute_and_solo(sounds_dir: Path) -> None:
    engine, backend, _, _ = make_engine(sounds_dir)
    engine.set_muted(True)
    assert engine.play(ev("harp")) == "muted"
    engine.set_muted(False)
    engine.set_solo("hiss")
    assert engine.play(ev("harp")) == "solo"
    engine.set_solo(None)
    engine.set_sound_muted("harp", True)
    assert engine.play(ev("harp")) == "sound_muted"
    assert backend.channels == []


def test_volume_chain_and_pan(sounds_dir: Path) -> None:
    engine, backend, _, _ = make_engine(sounds_dir, master_volume=0.5)
    engine.set_sound_volume("hiss", 0.8)
    engine.play(ev(volume=0.5, pan=1.0))
    channel = backend.channels[0]
    assert channel.volume == pytest.approx(0.5 * 0.8 * 0.5)
    assert channel.pan == 1.0


def test_pitched_sounds_are_shifted_and_cached(sounds_dir: Path) -> None:
    engine, backend, clock, _ = make_engine(sounds_dir, polyphony=8)
    engine.play(ev("harp", pitch=12))
    clock.now += 1
    engine.play(ev("harp", pitch=12))
    assert len(backend.loaded) == 1  # second play reused the handle
    assert len(backend.loaded[0]) == pytest.approx(4410 / 2, abs=2)  # octave up = half length


def test_missing_assets_do_not_crash_play(tmp_path: Path) -> None:
    engine, _, _, _ = make_engine(tmp_path)
    assert engine.play(ev()) == "missing_assets"


def test_ambient_fades_and_loops(sounds_dir: Path) -> None:
    engine, backend, clock, _ = make_engine(sounds_dir)
    engine.set_ambient(AmbientUpdate("bed", 1.0))
    clock.now += 1.0
    engine.tick()
    channel = backend.channels[0]
    assert channel.volume == pytest.approx(0.7 * 0.5 * 0.5)  # half-way through the fade
    clock.now += 5.0
    engine.tick()
    assert channel.volume == pytest.approx(0.7 * 0.5)  # master * sound volume * gain 1.0
    engine.tick()
    assert channel.queued  # next loop segment was queued
    engine.set_muted(True)
    assert channel.volume == 0.0


def test_state_reports_mixer(sounds_dir: Path) -> None:
    engine, _, _, _ = make_engine(sounds_dir)
    engine.set_solo("hiss")
    state = engine.state()
    assert state["solo"] == "hiss"
    assert state["per_sound"]["hiss"]["cooldown_s"] == 1.0


def test_unknown_sound_control_raises(sounds_dir: Path) -> None:
    engine, _, _, _ = make_engine(sounds_dir)
    with pytest.raises(KeyError):
        engine.set_sound_volume("nope", 0.5)


def test_ducker_scales_with_recent_rate() -> None:
    duck = Ducker(window_s=5, max_reduction_db=6, full_duck_rate=2)
    assert duck.gain("a", 0) == 1.0
    for i in range(10):  # 10 plays in 5s == 2/s == full duck
        duck.record("a", i * 0.5)
    assert duck.gain("a", 4.9) == pytest.approx(10 ** (-6 / 20))
    assert duck.gain("rare", 4.9) == 1.0  # other sounds unaffected
    assert duck.gain("a", 100) == 1.0  # window expired


def test_ducker_disabled() -> None:
    duck = Ducker(enabled=False)
    for i in range(50):
        duck.record("a", i * 0.01)
    assert duck.gain("a", 1.0) == 1.0
