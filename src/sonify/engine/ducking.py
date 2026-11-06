"""Volume ducking: sounds that fire often get quieter, so rare ones stand out."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Deque, Dict


class Ducker:
    """Per-sound gain reduction based on how often the sound played recently.

    A sound playing at ``full_duck_rate`` plays/second (or more) is reduced by
    ``max_reduction_db``; a sound that plays rarely is left at full volume.
    Reduction scales linearly in between. Because it is per sound, a busy
    harp does not make a once-a-minute bell quieter; it only makes the harp
    itself recede.
    """

    def __init__(
        self,
        window_s: float = 5.0,
        max_reduction_db: float = 9.0,
        full_duck_rate: float = 2.0,
        enabled: bool = True,
    ) -> None:
        self.window_s = window_s
        self.max_reduction_db = max_reduction_db
        self.full_duck_rate = full_duck_rate
        self.enabled = enabled
        self._plays: Dict[str, Deque[float]] = defaultdict(deque)

    def record(self, sound: str, now: float) -> None:
        self._plays[sound].append(now)

    def gain(self, sound: str, now: float) -> float:
        """Linear gain multiplier in (0, 1]."""
        if not self.enabled:
            return 1.0
        plays = self._plays[sound]
        while plays and now - plays[0] > self.window_s:
            plays.popleft()
        rate = len(plays) / self.window_s
        fraction = min(1.0, rate / self.full_duck_rate)
        return 10 ** (-(self.max_reduction_db * fraction) / 20)
