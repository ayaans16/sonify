"""Loads converted WAV files from ./sounds/ into memory."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np
import soundfile as sf


class MissingAssetsError(Exception):
    """Sound files are missing; the message tells the user how to fix it."""


class SoundBank:
    """Lazy cache of ``sound id -> list of int16 (frames, 2) variants``."""

    def __init__(self, sounds_dir: Path) -> None:
        self.sounds_dir = Path(sounds_dir)
        self._cache: Dict[str, List[np.ndarray]] = {}

    def available(self) -> List[str]:
        if not self.sounds_dir.is_dir():
            return []
        return sorted(p.name for p in self.sounds_dir.iterdir() if any(p.glob("*.wav")))

    def missing(self, sound_ids: Iterable[str]) -> List[str]:
        have = set(self.available())
        return sorted(s for s in set(sound_ids) if s not in have)

    def require(self, sound_ids: Iterable[str]) -> None:
        """Raise ``MissingAssetsError`` unless every id has files on disk."""
        if not self.sounds_dir.is_dir():
            raise MissingAssetsError(
                f"No sounds folder at {self.sounds_dir}. "
                "Run `sonify setup` to extract sounds from your Minecraft install."
            )
        missing = self.missing(sound_ids)
        if missing:
            raise MissingAssetsError(
                f"Missing sound files for: {', '.join(missing)}.\n"
                "Run `sonify setup` (use --force to redo it); if a sound failed to "
                "resolve there, fix its `key` in config.yaml."
            )

    def variants(self, sound_id: str) -> List[np.ndarray]:
        if sound_id not in self._cache:
            self.require([sound_id])
            files = sorted((self.sounds_dir / sound_id).glob("*.wav"))
            self._cache[sound_id] = [
                sf.read(str(f), dtype="int16", always_2d=True)[0] for f in files
            ]
        return self._cache[sound_id]
