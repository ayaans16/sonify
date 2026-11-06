"""Plain data types passed between sources, the mapper and the engine."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Union


@dataclass(frozen=True)
class Sample:
    """One metric reading produced by a source."""

    signal: str
    value: float
    unit: str = ""
    host: str = "local"
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class SoundEvent:
    """A discrete sound the mapper wants the engine to play."""

    sound: str
    signal: str
    value: float
    rule: str = ""
    #: Semitones relative to the sample's native pitch (pitched sounds only).
    pitch: Optional[int] = None
    volume: float = 1.0
    #: -1.0 (left) .. 1.0 (right).
    pan: float = 0.0
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class AmbientUpdate:
    """Sets the target gain of a looping ambient bed."""

    sound: str
    gain: float
    signal: str = ""


Action = Union[SoundEvent, AmbientUpdate]
