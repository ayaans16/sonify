"""Wires sources -> mapper -> engine and runs the main loop."""

from __future__ import annotations

import logging
import queue
import threading
from typing import Iterable, List, Optional

from .bus import EventBus
from .config import Config
from .engine import Engine
from .mapper import Mapper, referenced_sounds
from .models import Action, AmbientUpdate, Sample, SoundEvent
from .sources import Source, build_sources, unknown_signals

log = logging.getLogger(__name__)

TICK_S = 0.05


class Daemon:
    def __init__(
        self,
        config: Config,
        engine: Engine,
        mapper: Mapper,
        bus: EventBus,
        sources: Optional[List[Source]] = None,
    ) -> None:
        self.config = config
        self.engine = engine
        self.mapper = mapper
        self.bus = bus
        self.sources = sources if sources is not None else build_sources(config)
        self.revision = 0
        self._samples: "queue.Queue[Sample]" = queue.Queue(maxsize=1000)
        self._stop = threading.Event()

    def apply_config(self, config: Config) -> None:
        """Hot-reload: swap the mapper and engine settings in place."""
        self.config = config
        self.mapper.set_config(config)
        self.engine.apply_config(config)
        self._dispatch(self.mapper.baseline())
        self.revision += 1
        self.bus.publish("config", {"revision": self.revision})

    def run(self) -> None:
        """Run until ``stop()`` is called. Blocks the calling thread."""
        for name in unknown_signals(self.config):
            log.warning("signal '%s' has no source and will never fire", name)
        self._dispatch(self.mapper.baseline())
        for source in self.sources:
            source.start(self._offer)
        try:
            while not self._stop.is_set():
                self._step()
        finally:
            for source in self.sources:
                source.stop()
            self.engine.close()

    def stop(self) -> None:
        self._stop.set()

    def _offer(self, sample: Sample) -> None:
        try:
            self._samples.put_nowait(sample)
        except queue.Full:
            pass  # drop: stale readings are worthless

    def _step(self) -> None:
        try:
            sample: Optional[Sample] = self._samples.get(timeout=TICK_S)
        except queue.Empty:
            sample = None
        while sample is not None:
            self._dispatch(self.mapper.update(sample))
            try:
                sample = self._samples.get_nowait()
            except queue.Empty:
                sample = None
        self._dispatch(self.mapper.tick())
        self.engine.tick()

    def _dispatch(self, actions: Iterable[Action]) -> None:
        for action in actions:
            if isinstance(action, AmbientUpdate):
                self.engine.set_ambient(action)
            elif isinstance(action, SoundEvent):
                self.engine.play(action)
