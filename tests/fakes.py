from __future__ import annotations

from typing import Any, List, Optional

import numpy as np


class FakeChannel:
    def __init__(self, sound: Any, volume: float, pan: float) -> None:
        self.sound, self.volume, self.pan = sound, volume, pan
        self.busy = True
        self.queued: List[Any] = []


class FakeBackend:
    """Records what the engine asks the audio layer to do."""

    def __init__(self, channels: int = 64) -> None:
        self.loaded: List[np.ndarray] = []
        self.channels: List[FakeChannel] = []
        self.max_channels = channels
        self.closed = False

    def load(self, samples: np.ndarray) -> Any:
        self.loaded.append(samples)
        return len(self.loaded) - 1

    def play(self, sound: Any, volume: float, pan: float) -> Optional[FakeChannel]:
        if sum(c.busy for c in self.channels) >= self.max_channels:
            return None
        channel = FakeChannel(sound, volume, pan)
        self.channels.append(channel)
        return channel

    def set_volume(self, channel: FakeChannel, volume: float, pan: float) -> None:
        channel.volume, channel.pan = volume, pan

    def queue(self, channel: FakeChannel, sound: Any) -> None:
        channel.queued.append(sound)

    def needs_queue(self, channel: FakeChannel) -> bool:
        return channel.busy and not channel.queued

    def is_busy(self, channel: FakeChannel) -> bool:
        return channel.busy

    def stop(self, channel: FakeChannel) -> None:
        channel.busy = False

    def close(self) -> None:
        self.closed = True
