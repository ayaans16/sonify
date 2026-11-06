"""Thin wrapper over pygame.mixer so the engine can be tested with a fake."""

from __future__ import annotations

from typing import Any, Optional, Protocol

import numpy as np


class Backend(Protocol):
    def load(self, samples: np.ndarray) -> Any: ...
    def play(self, sound: Any, volume: float, pan: float) -> Optional[Any]: ...
    def set_volume(self, channel: Any, volume: float, pan: float) -> None: ...
    def queue(self, channel: Any, sound: Any) -> None: ...
    def needs_queue(self, channel: Any) -> bool: ...
    def is_busy(self, channel: Any) -> bool: ...
    def stop(self, channel: Any) -> None: ...
    def close(self) -> None: ...


def _stereo(volume: float, pan: float) -> "tuple[float, float]":
    left = volume * (1.0 - max(0.0, pan))
    right = volume * (1.0 + min(0.0, pan))
    return left, right


class PygameBackend:
    """44.1 kHz stereo 16-bit output through pygame.mixer."""

    def __init__(self, channels: int = 32) -> None:
        import pygame

        self._pg = pygame
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.mixer.init()
        pygame.mixer.set_num_channels(channels)

    def load(self, samples: np.ndarray) -> Any:
        return self._pg.mixer.Sound(buffer=np.ascontiguousarray(samples).tobytes())

    def play(self, sound: Any, volume: float, pan: float) -> Optional[Any]:
        channel = self._pg.mixer.find_channel()
        if channel is None:
            return None
        channel.set_volume(*_stereo(volume, pan))
        channel.play(sound)
        return channel

    def set_volume(self, channel: Any, volume: float, pan: float) -> None:
        channel.set_volume(*_stereo(volume, pan))

    def queue(self, channel: Any, sound: Any) -> None:
        channel.queue(sound)

    def needs_queue(self, channel: Any) -> bool:
        return channel.get_busy() and channel.get_queue() is None

    def is_busy(self, channel: Any) -> bool:
        return bool(channel.get_busy())

    def stop(self, channel: Any) -> None:
        channel.stop()

    def close(self) -> None:
        self._pg.mixer.quit()
