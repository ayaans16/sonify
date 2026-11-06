"""The mixer: polyphony, cooldowns, ducking, pan, ambient beds, mute/solo.

Design notes
------------
* The mapper decides *when* something should sound; the engine decides
  whether it *may*. Per-sound cooldowns and a global events-per-second cap
  live here so a misbehaving rule can never turn into noise.
* Everything reaches the speakers through a ``Backend`` (pygame in
  production, a fake in tests). Time comes from an injectable clock.
* Public methods take a re-entrant lock: the daemon thread plays sounds
  while the dashboard's request threads change volume, mute and so on.
* The engine publishes ``sound`` and ``state`` events to the bus. It never
  reads from it.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from ..bus import EventBus
from ..config import Config
from ..models import AmbientUpdate, SoundEvent
from .backend import Backend
from .bank import MissingAssetsError, SoundBank
from .ducking import Ducker
from .pitch import shift

log = logging.getLogger(__name__)

AMBIENT_FADE_PER_S = 0.5  # gain units per second when an ambient bed moves
STATE_MIN_INTERVAL_S = 0.25
HANDLE_CACHE_SIZE = 256


@dataclass
class _Voice:
    sound: str
    channel: Any
    started: float


@dataclass
class _Loop:
    sound: str
    current: float = 0.0
    target: float = 0.0
    channel: Any = None


class Engine:
    def __init__(
        self,
        config: Config,
        bank: SoundBank,
        backend: Backend,
        bus: Optional[EventBus] = None,
        clock: Callable[[], float] = time.monotonic,
        rng: Optional[random.Random] = None,
    ) -> None:
        self._bank = bank
        self._backend = backend
        self._bus = bus
        self._clock = clock
        self._rng = rng or random.Random()
        self._lock = threading.RLock()

        self._voices: List[_Voice] = []
        self._loops: Dict[str, _Loop] = {}
        self._last_played: Dict[str, float] = {}
        self._recent: Deque[float] = deque()
        self._handles: "OrderedDict[Tuple[str, int, int], Any]" = OrderedDict()
        self._warned: set = set()

        self._muted = False
        self._solo: Optional[str] = None
        self._last_tick = clock()
        self._last_state_at = 0.0
        self._last_state: Optional[dict] = None

        self.apply_config(config)

    # ------------------------------------------------------------ config

    def apply_config(self, config: Config) -> None:
        """(Re)load settings. Runtime mixer tweaks for unchanged ids survive."""
        with self._lock:
            old_volumes = getattr(self, "_volumes", {})
            old_cooldowns = getattr(self, "_cooldowns", {})
            old_muted = getattr(self, "_sound_muted", {})
            self._config = config
            self._master = config.master_volume
            self._volumes = {k: old_volumes.get(k, s.volume) for k, s in config.sounds.items()}
            self._cooldowns = {k: old_cooldowns.get(k, s.cooldown_s) for k, s in config.sounds.items()}
            self._sound_muted = {k: old_muted.get(k, False) for k in config.sounds}
            self._ducker = Ducker(
                window_s=config.ducking.window_s,
                max_reduction_db=config.ducking.max_reduction_db,
                full_duck_rate=config.ducking.full_duck_rate,
                enabled=config.ducking.enabled,
            )
            self._max_voices = config.polyphony
            self._max_rate = config.max_events_per_s
            if self._solo not in config.sounds:
                self._solo = None
        self._publish_state(force=True)

    # --------------------------------------------------------- controls

    def set_master_volume(self, volume: float) -> None:
        with self._lock:
            self._master = min(1.0, max(0.0, volume))
            self._refresh_loop_volumes()
        self._publish_state(force=True)

    def set_muted(self, muted: bool) -> None:
        with self._lock:
            self._muted = muted
            self._refresh_loop_volumes()
        self._publish_state(force=True)

    def set_sound_volume(self, sound: str, volume: float) -> None:
        with self._lock:
            self._require_known(sound)
            self._volumes[sound] = min(1.0, max(0.0, volume))
            self._refresh_loop_volumes()
        self._publish_state(force=True)

    def set_sound_muted(self, sound: str, muted: bool) -> None:
        with self._lock:
            self._require_known(sound)
            self._sound_muted[sound] = muted
            self._refresh_loop_volumes()
        self._publish_state(force=True)

    def set_solo(self, sound: Optional[str]) -> None:
        with self._lock:
            if sound is not None:
                self._require_known(sound)
            self._solo = sound
            self._refresh_loop_volumes()
        self._publish_state(force=True)

    def set_cooldown(self, sound: str, seconds: float) -> None:
        with self._lock:
            self._require_known(sound)
            self._cooldowns[sound] = max(0.0, seconds)
        self._publish_state(force=True)

    def _require_known(self, sound: str) -> None:
        if sound not in self._config.sounds:
            raise KeyError(sound)

    @property
    def bank(self) -> SoundBank:
        return self._bank

    @property
    def muted(self) -> bool:
        return self._muted

    @property
    def master_volume(self) -> float:
        return self._master

    # ------------------------------------------------------------- play

    def play(self, event: SoundEvent, force: bool = False) -> Optional[str]:
        """Play ``event`` if allowed. Returns the suppression reason, or None.

        ``force`` skips the cooldown and rate limit (used for previews); mute
        and solo still apply.
        """
        with self._lock:
            reason = self._try_play(event, force)
        if self._bus is not None:
            self._bus.publish(
                "sound",
                {
                    "sound": event.sound,
                    "signal": event.signal,
                    "trigger_value": event.value,
                    "rule": event.rule,
                    "volume": event.volume,
                    "pitch": event.pitch,
                    "suppressed": reason,
                },
            )
        self._publish_state()
        return reason

    def _try_play(self, event: SoundEvent, force: bool = False) -> Optional[str]:
        sound_def = self._config.sounds.get(event.sound)
        if sound_def is None:
            return "unknown_sound"
        if self._muted:
            return "muted"
        if self._sound_muted.get(event.sound):
            return "sound_muted"
        if self._solo is not None and self._solo != event.sound:
            return "solo"

        now = self._clock()
        while self._recent and now - self._recent[0] > 1.0:
            self._recent.popleft()
        if not force:
            if now - self._last_played.get(event.sound, -1e9) < self._cooldowns[event.sound]:
                return "cooldown"
            if len(self._recent) >= self._max_rate:
                return "rate_limit"

        try:
            handle = self._handle_for(event.sound, event.pitch)
        except MissingAssetsError as exc:
            self._warn_once(event.sound, str(exc))
            return "missing_assets"

        self._prune_voices()
        if len(self._voices) >= self._max_voices:
            oldest = self._voices.pop(0)  # steal the longest-running voice
            self._backend.stop(oldest.channel)

        volume = self._oneshot_volume(event, now)
        channel = self._backend.play(handle, volume, event.pan)
        if channel is None:
            return "no_channel"
        self._voices.append(_Voice(event.sound, channel, now))
        self._last_played[event.sound] = now
        self._recent.append(now)
        self._ducker.record(event.sound, now)
        return None

    def _oneshot_volume(self, event: SoundEvent, now: float) -> float:
        gain = (
            self._master
            * self._volumes[event.sound]
            * event.volume
            * self._ducker.gain(event.sound, now)
        )
        return min(1.0, max(0.0, gain))

    def _handle_for(self, sound: str, semitones: Optional[int]) -> Any:
        variants = self._bank.variants(sound)
        index = self._rng.randrange(len(variants))
        pitch = int(semitones or 0)
        key = (sound, index, pitch)
        if key in self._handles:
            self._handles.move_to_end(key)
            return self._handles[key]
        samples = variants[index]
        if self._config.sounds[sound].kind == "pitched" and pitch:
            samples = shift(samples, pitch)
        handle = self._backend.load(samples)
        self._handles[key] = handle
        if len(self._handles) > HANDLE_CACHE_SIZE:
            self._handles.popitem(last=False)
        return handle

    def _prune_voices(self) -> None:
        self._voices = [v for v in self._voices if self._backend.is_busy(v.channel)]

    # ---------------------------------------------------------- ambient

    def set_ambient(self, update: AmbientUpdate) -> None:
        with self._lock:
            if update.sound not in self._config.sounds:
                self._warn_once(update.sound, f"ambient sound '{update.sound}' is not defined in config")
                return
            loop = self._loops.setdefault(update.sound, _Loop(update.sound))
            loop.target = min(1.0, max(0.0, update.gain))

    def tick(self) -> None:
        """Advance fades, keep loops running, drop finished voices."""
        with self._lock:
            now = self._clock()
            dt = max(0.0, now - self._last_tick)
            self._last_tick = now
            step = AMBIENT_FADE_PER_S * dt
            for loop in self._loops.values():
                delta = loop.target - loop.current
                loop.current += max(-step, min(step, delta))
                self._service_loop(loop)
            self._prune_voices()
        self._publish_state()

    def _service_loop(self, loop: _Loop) -> None:
        volume = self._loop_volume(loop)
        if loop.channel is not None and not self._backend.is_busy(loop.channel):
            loop.channel = None
        if loop.channel is None:
            if loop.current <= 0.0:
                return
            try:
                variants = self._bank.variants(loop.sound)
            except MissingAssetsError as exc:
                self._warn_once(loop.sound, str(exc))
                return
            loop.channel = self._backend.play(self._loop_handle(loop.sound, variants), volume, 0.0)
        else:
            self._backend.set_volume(loop.channel, volume, 0.0)
            if self._backend.needs_queue(loop.channel):
                variants = self._bank.variants(loop.sound)
                self._backend.queue(loop.channel, self._loop_handle(loop.sound, variants))

    def _loop_handle(self, sound: str, variants: List[Any]) -> Any:
        index = self._rng.randrange(len(variants))
        key = (sound, index, 0)
        if key not in self._handles:
            self._handles[key] = self._backend.load(variants[index])
        return self._handles[key]

    def _loop_volume(self, loop: _Loop) -> float:
        if self._muted or self._sound_muted.get(loop.sound):
            return 0.0
        if self._solo is not None and self._solo != loop.sound:
            return 0.0
        return min(1.0, max(0.0, self._master * self._volumes[loop.sound] * loop.current))

    def _refresh_loop_volumes(self) -> None:
        for loop in self._loops.values():
            if loop.channel is not None:
                self._backend.set_volume(loop.channel, self._loop_volume(loop), 0.0)

    # ------------------------------------------------------------ state

    def state(self) -> Dict[str, Any]:
        with self._lock:
            self._prune_voices()
            active: List[Dict[str, Any]] = [
                {"sound": v.sound, "kind": "oneshot"} for v in self._voices
            ]
            active += [
                {"sound": l.sound, "kind": "loop", "gain": round(l.current, 2)}
                for l in self._loops.values()
                if l.channel is not None
            ]
            return {
                "volume": round(self._master, 3),
                "muted": self._muted,
                "solo": self._solo,
                "active": active,
                "per_sound": {
                    sid: {
                        "volume": round(self._volumes[sid], 3),
                        "muted": self._sound_muted[sid],
                        "cooldown_s": self._cooldowns[sid],
                        "kind": sdef.kind,
                    }
                    for sid, sdef in self._config.sounds.items()
                },
            }

    def _publish_state(self, force: bool = False) -> None:
        if self._bus is None:
            return
        now = self._clock()
        if not force and now - self._last_state_at < STATE_MIN_INTERVAL_S:
            return
        state = self.state()
        if not force and state == self._last_state:
            return
        self._last_state, self._last_state_at = state, now
        self._bus.publish("state", state)

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning(message)

    def close(self) -> None:
        with self._lock:
            for voice in self._voices:
                self._backend.stop(voice.channel)
            for loop in self._loops.values():
                if loop.channel is not None:
                    self._backend.stop(loop.channel)
            self._backend.close()
