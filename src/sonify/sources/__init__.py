"""Pluggable metric sources."""

from __future__ import annotations

from typing import List, Set

from ..config import Config
from .base import PollingSource, Source
from .psutil_source import ALL_SIGNALS as PSUTIL_SIGNALS
from .psutil_source import PsutilSource

__all__ = ["PollingSource", "PsutilSource", "Source", "build_sources", "unknown_signals"]

_PROVIDED: Set[str] = set(PSUTIL_SIGNALS)


def build_sources(config: Config) -> List[Source]:
    """Create the sources needed for the signals used in ``config``."""
    wanted = [s for s in config.signals if s in PSUTIL_SIGNALS]
    return [PsutilSource(signals=wanted)] if wanted else []


def unknown_signals(config: Config) -> List[str]:
    """Signals in the config that no built-in source provides."""
    return sorted(s for s in config.signals if s not in _PROVIDED)
