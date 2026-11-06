from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import List

import numpy as np
import soundfile as sf

from sonify.bus import EventBus
from sonify.config import parse_config
from sonify.daemon import Daemon
from sonify.engine import Engine, SoundBank
from sonify.mapper import Mapper
from sonify.models import Sample
from sonify.sources.base import EmitFn, Source

from fakes import FakeBackend


class OneShotSource(Source):
    name = "test"

    def __init__(self, samples: List[Sample]) -> None:
        self.samples = samples

    def start(self, emit: EmitFn) -> None:
        for s in self.samples:
            emit(s)

    def stop(self) -> None:
        pass


def test_sample_flows_to_engine_and_bus(tmp_path: Path) -> None:
    folder = tmp_path / "hiss"
    folder.mkdir()
    tone = np.zeros(4410, dtype=np.float32)
    sf.write(str(folder / "1.wav"), np.stack([tone, tone], axis=1), 44100, subtype="PCM_16")

    config = parse_config(
        {
            "sounds": {"hiss": {"key": "x"}},
            "signals": {"net_errors": {"events": [{"sound": "hiss", "when": {"above": 1}, "cooldown_s": 5}]}},
        }
    )
    bus, seen = EventBus(), []
    bus.subscribe(seen.append)
    backend = FakeBackend()
    engine = Engine(config, SoundBank(tmp_path), backend, bus)
    daemon = Daemon(config, engine, Mapper(config, bus), bus, sources=[OneShotSource([Sample("net_errors", 3.0)])])

    thread = threading.Thread(target=daemon.run)
    thread.start()
    deadline = time.time() + 3
    while not backend.channels and time.time() < deadline:
        time.sleep(0.02)
    daemon.stop()
    thread.join(timeout=3)

    assert len(backend.channels) == 1
    types = {e.type for e in seen}
    assert {"metric", "sound"} <= types
    assert backend.closed
