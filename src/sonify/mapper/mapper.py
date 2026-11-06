"""The mapper: config + metric samples -> sound actions.

Design notes
------------
* ``update(sample)`` reacts to a new reading (ambient gain, threshold rules);
  ``tick()`` is time-driven and emits the rhythmic ``pitch_tempo`` notes.
  Both are pure functions of state plus an injectable clock, so they are
  easy to test without waiting.
* A threshold rule is a small state machine. It becomes *active* when the
  value crosses ``above`` / ``below`` and only goes inactive again after
  moving ``hysteresis`` back past the threshold, so a value hovering at the
  line cannot flap. While active it fires, then repeats every ``cooldown_s``:
  a persistent problem keeps nagging, at a calm rate.
* The mapper never plays audio. It returns actions and publishes the raw
  readings to the bus; the engine does the rest.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Set, Tuple

from ..bus import EventBus
from ..config import Config, EventRule, When
from ..models import Action, AmbientUpdate, Sample, SoundEvent
from .scale import note_to_midi, quantize_to_scale, scale_intervals

log = logging.getLogger(__name__)

#: MIDI note of the Minecraft note-block samples at their native pitch (F#4).
SAMPLE_ROOT_MIDI = 66


@dataclass
class _RuleState:
    active: bool = False
    last_fired: float = -math.inf
    next_due: float = -math.inf


def referenced_sounds(config: Config) -> Set[str]:
    """Every sound id the config can ask the engine to play."""
    ids: Set[str] = {b.sound for b in config.ambient_baseline}
    for signal in config.signals.values():
        if signal.ambient:
            ids.add(signal.ambient.sound)
        ids.update(rule.sound for rule in signal.events)
    return ids


def root_pitch(config: Config) -> int:
    """Semitone shift that makes a note-block sample sound at the scale root."""
    return note_to_midi(config.pitched.root) - SAMPLE_ROOT_MIDI


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _unit(value: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 0.0
    return min(1.0, max(0.0, (value - lo) / (hi - lo)))


def _is_active(when: Optional[When], was_active: bool, value: float) -> bool:
    """Threshold test with hysteresis latch."""
    if when is None:
        return True
    above, below, hyst = when.above, when.below, when.hysteresis
    if (above is not None and value >= above) or (below is not None and value <= below):
        return True
    if not was_active:
        return False
    return (above is not None and value >= above - hyst) or (
        below is not None and value <= below + hyst
    )


class Mapper:
    def __init__(
        self,
        config: Config,
        bus: Optional[EventBus] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bus = bus
        self._clock = clock
        self._lock = threading.RLock()
        self._warned: Set[str] = set()
        self.set_config(config)

    def set_config(self, config: Config) -> None:
        with self._lock:
            self._config = config
            self._states: Dict[Tuple[str, int], _RuleState] = {}
            self._values: Dict[str, float] = {}

    # ------------------------------------------------------------ inputs

    def baseline(self) -> List[Action]:
        """Always-on ambient beds; call at start and after a config reload."""
        with self._lock:
            return [AmbientUpdate(b.sound, b.gain) for b in self._config.ambient_baseline]

    def update(self, sample: Sample) -> List[Action]:
        """Handle a new reading; returns ambient updates and threshold events."""
        if self._bus is not None:
            self._bus.publish(
                "metric",
                {"signal": sample.signal, "value": sample.value, "unit": sample.unit, "host": sample.host},
            )
        with self._lock:
            now = self._clock()
            self._values[sample.signal] = sample.value
            signal = self._config.signals.get(sample.signal)
            if signal is None:
                return []

            actions: List[Action] = []
            if signal.ambient is not None:
                gain = signal.ambient.gain
                if gain is None:
                    level = 1.0
                else:
                    t = _unit(sample.value, gain.min_value, gain.max_value)
                    level = _lerp(gain.min_gain, gain.max_gain, t)
                actions.append(AmbientUpdate(signal.ambient.sound, level, sample.signal))

            for index, rule in enumerate(signal.events):
                state = self._states.setdefault((sample.signal, index), _RuleState())
                state.active = _is_active(rule.when, state.active, sample.value)
                if rule.mode != "threshold" or rule.when is None or not state.active:
                    continue
                if now - state.last_fired >= rule.cooldown_s:
                    state.last_fired = now
                    actions.append(
                        SoundEvent(
                            sound=rule.sound,
                            signal=sample.signal,
                            value=sample.value,
                            rule=f"{sample.signal}[{index}]",
                            volume=rule.volume,
                            pan=0.0,
                        )
                    )
            return actions

    def tick(self) -> List[Action]:
        """Emit due ``pitch_tempo`` notes. Call often (~20 Hz)."""
        with self._lock:
            now = self._clock()
            actions: List[Action] = []
            for name, signal in self._config.signals.items():
                value = self._values.get(name)
                if value is None:
                    continue
                for index, rule in enumerate(signal.events):
                    if rule.mode != "pitch_tempo":
                        continue
                    state = self._states.setdefault((name, index), _RuleState())
                    if not state.active or now < state.next_due:
                        continue
                    note = self._note(name, index, rule, value, now, state)
                    if note is not None:
                        actions.append(note)
            return actions

    def _note(
        self, signal: str, index: int, rule: EventRule, value: float, now: float, state: _RuleState
    ) -> Optional[SoundEvent]:
        if rule.pitch is None or rule.interval_s is None:
            self._warn_once(f"{signal}[{index}]", f"{signal}[{index}]: pitch_tempo needs pitch and interval_s")
            state.next_due = now + 5.0
            return None
        cfg = self._config.pitched
        t = _unit(value, rule.pitch.from_, rule.pitch.to)
        state.next_due = now + max(0.05, _lerp(rule.interval_s.from_, rule.interval_s.to, t))
        try:
            intervals = scale_intervals(cfg.scale)
            root = note_to_midi(cfg.root)
        except ValueError as exc:
            self._warn_once("pitched", str(exc))
            return None
        try:
            offset = quantize_to_scale(value, rule.pitch.from_, rule.pitch.to, intervals, cfg.range_octaves)
        except NotImplementedError:
            self._warn_once(
                "quantize",
                "quantize_to_scale is not implemented yet; pitched notes will stay on the root note",
            )
            offset = 0
        return SoundEvent(
            sound=rule.sound,
            signal=signal,
            value=value,
            rule=f"{signal}[{index}]",
            pitch=root + offset - SAMPLE_ROOT_MIDI,
            volume=rule.volume,
        )

    # ------------------------------------------------------------- info

    def describe(self) -> List[Dict[str, str]]:
        """Human-readable mapping summary (used by `sonify list` and the UI)."""
        rows: List[Dict[str, str]] = []
        with self._lock:
            for name, signal in self._config.signals.items():
                if signal.ambient:
                    rows.append({"signal": name, "sound": signal.ambient.sound, "rule": "ambient bed"})
                for rule in signal.events:
                    rows.append({"signal": name, "sound": rule.sound, "rule": _describe_rule(rule)})
        return rows

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning(message)


def _describe_rule(rule: EventRule) -> str:
    parts: List[str] = []
    if rule.mode == "pitch_tempo":
        parts.append("pitch+tempo")
    if rule.when:
        if rule.when.above is not None:
            parts.append(f"above {rule.when.above:g}")
        if rule.when.below is not None:
            parts.append(f"below {rule.when.below:g}")
        if rule.when.hysteresis:
            parts.append(f"hysteresis {rule.when.hysteresis:g}")
    if rule.mode == "threshold":
        parts.append(f"every {rule.cooldown_s:g}s")
    return ", ".join(parts)
