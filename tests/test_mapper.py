from __future__ import annotations

from typing import List

import pytest

from sonify.bus import Event, EventBus
from sonify.config import parse_config
from sonify.mapper import Mapper, referenced_sounds, root_pitch
from sonify.mapper import mapper as mapper_module
from sonify.models import AmbientUpdate, Sample, SoundEvent


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def build(signals: dict, **extra):
    raw = {
        "sounds": {
            "bell": {"key": "b"},
            "harp": {"key": "h", "kind": "pitched"},
            "bed": {"key": "c", "kind": "loop"},
        },
        "signals": signals,
        **extra,
    }
    clock = Clock()
    return Mapper(parse_config(raw), clock=clock), clock


def sample(signal: str, value: float) -> Sample:
    return Sample(signal=signal, value=value)


def events(actions) -> List[SoundEvent]:
    return [a for a in actions if isinstance(a, SoundEvent)]


MEM = {"mem": {"events": [{"sound": "bell", "when": {"above": 85, "hysteresis": 5}, "cooldown_s": 30}]}}


def test_threshold_fires_only_above() -> None:
    mapper, _ = build(MEM)
    assert events(mapper.update(sample("mem", 84.9))) == []
    fired = events(mapper.update(sample("mem", 85)))
    assert [e.sound for e in fired] == ["bell"]
    assert fired[0].value == 85 and fired[0].signal == "mem"


def test_below_threshold() -> None:
    mapper, _ = build({"disk_free": {"events": [{"sound": "bell", "when": {"below": 10}, "cooldown_s": 5}]}})
    assert events(mapper.update(sample("disk_free", 50))) == []
    assert len(events(mapper.update(sample("disk_free", 9)))) == 1


def test_cooldown_repeats_while_condition_holds() -> None:
    mapper, clock = build(MEM)
    assert len(events(mapper.update(sample("mem", 90)))) == 1
    clock.now += 29
    assert events(mapper.update(sample("mem", 90))) == []  # still cooling down
    clock.now += 2
    assert len(events(mapper.update(sample("mem", 90)))) == 1  # reminder after 30s


def test_hysteresis_keeps_rule_active_until_clearly_below() -> None:
    mapper, clock = build(MEM)
    mapper.update(sample("mem", 90))
    clock.now += 31
    # 82 is under the 85 line but within the 5-point hysteresis band: still active.
    assert len(events(mapper.update(sample("mem", 82)))) == 1
    clock.now += 31
    # 79 is below 85 - 5: rule deactivates, nothing fires.
    assert events(mapper.update(sample("mem", 79))) == []
    clock.now += 31
    # Back at 82 it is NOT active again: needs to cross 85 to re-arm.
    assert events(mapper.update(sample("mem", 82))) == []


def test_recrossing_fires_immediately_after_clearing() -> None:
    mapper, clock = build(MEM)
    mapper.update(sample("mem", 90))
    mapper.update(sample("mem", 50))
    clock.now += 31  # cooldown elapsed while healthy
    assert len(events(mapper.update(sample("mem", 95)))) == 1


def test_unmapped_signal_is_ignored() -> None:
    mapper, _ = build(MEM)
    assert mapper.update(sample("nothing", 1)) == []


def test_ambient_gain_is_linear_and_clamped() -> None:
    mapper, _ = build(
        {"cpu": {"ambient": {"sound": "bed", "gain": {"min_value": 0, "max_value": 100, "min": 0.2, "max": 1.0}}}}
    )

    def gain(v: float) -> float:
        (action,) = mapper.update(sample("cpu", v))
        assert isinstance(action, AmbientUpdate) and action.sound == "bed"
        return action.gain

    assert gain(0) == pytest.approx(0.2)
    assert gain(50) == pytest.approx(0.6)
    assert gain(100) == pytest.approx(1.0)
    assert gain(400) == pytest.approx(1.0)


def test_baseline_ambient() -> None:
    mapper, _ = build({}, ambient_baseline=[{"sound": "bed", "gain": 0.4}])
    assert mapper.baseline() == [AmbientUpdate("bed", 0.4)]


CPU = {
    "cpu": {
        "events": [
            {
                "sound": "harp",
                "mode": "pitch_tempo",
                "when": {"above": 25, "hysteresis": 5},
                "pitch": {"from": 25, "to": 100},
                "interval_s": {"from": 2.0, "to": 0.5},
            }
        ]
    }
}


def test_pitch_tempo_is_silent_when_idle() -> None:
    mapper, clock = build(CPU)
    mapper.update(sample("cpu", 10))
    clock.now += 10
    assert mapper.tick() == []


def test_pitch_tempo_speeds_up_with_load() -> None:
    mapper, clock = build(CPU)

    def count_notes(load: float, seconds: float = 10.0) -> int:
        mapper.update(sample("cpu", load))
        n, end = 0, clock.now + seconds
        while clock.now < end:
            n += len(events(mapper.tick()))
            clock.now += 0.05
        return n

    low, high = count_notes(30), count_notes(95)
    assert high > low * 2


def test_pitch_goes_through_quantizer(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_quantize(value, lo, hi, intervals, octaves):
        calls.append((value, lo, hi, tuple(intervals), octaves))
        return 7

    monkeypatch.setattr(mapper_module, "quantize_to_scale", fake_quantize)
    mapper, _ = build(CPU, pitched={"scale": "pentatonic_minor", "root": "D3", "range_octaves": 2})
    mapper.update(sample("cpu", 60))
    (note,) = events(mapper.tick())
    assert calls == [(60, 25, 100, (0, 3, 5, 7, 10), 2)]
    assert note.pitch == 50 + 7 - mapper_module.SAMPLE_ROOT_MIDI


def test_unimplemented_quantizer_falls_back_to_root_note() -> None:
    mapper, _ = build(CPU)
    mapper.update(sample("cpu", 60))
    (note,) = events(mapper.tick())
    assert note.pitch == root_pitch(mapper._config)


def test_pitch_tempo_ignored_by_update_threshold_path() -> None:
    mapper, _ = build(CPU)
    assert events(mapper.update(sample("cpu", 90))) == []  # notes come from tick() only


def test_metrics_published_to_bus() -> None:
    bus, seen = EventBus(), []
    bus.subscribe(seen.append)
    mapper = Mapper(parse_config({}), bus=bus)
    mapper.update(Sample("cpu", 12.5, "%"))
    assert seen[0].type == "metric"
    assert seen[0].data == {"signal": "cpu", "value": 12.5, "unit": "%", "host": "local"}


def test_referenced_sounds_and_describe() -> None:
    mapper, _ = build({**MEM, **CPU}, ambient_baseline=[{"sound": "bed"}])
    assert referenced_sounds(mapper._config) == {"bell", "harp", "bed"}
    rows = mapper.describe()
    assert {"signal": "mem", "sound": "bell", "rule": "above 85, hysteresis 5, every 30s"} in rows
