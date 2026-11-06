"""Source interface.

A source pushes ``Sample`` objects into an ``emit`` callback from whatever
thread it likes. ``PollingSource`` covers the common "read something every N
seconds" case; event-driven sources (Docker events, log tailing) can subclass
``Source`` directly and call ``emit`` whenever something happens.
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from typing import Callable, List, Optional

from ..models import Sample

log = logging.getLogger(__name__)

EmitFn = Callable[[Sample], None]


class Source(ABC):
    name: str = "source"

    @abstractmethod
    def start(self, emit: EmitFn) -> None:
        """Begin producing samples. Must not block."""

    @abstractmethod
    def stop(self) -> None:
        """Stop producing samples and release resources."""

    def signals(self) -> List[str]:
        """Signal names this source can emit (used to validate the config)."""
        return []


class PollingSource(Source):
    interval_s: float = 1.0

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @abstractmethod
    def collect(self) -> List[Sample]:
        """Take one reading of every signal."""

    def start(self, emit: EmitFn) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(emit,), name=f"source-{self.name}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_s + 1)
            self._thread = None

    def _run(self, emit: EmitFn) -> None:
        while not self._stop.is_set():
            try:
                for sample in self.collect():
                    emit(sample)
            except Exception:
                log.exception("source %s failed to collect", self.name)
            self._stop.wait(self.interval_s)
