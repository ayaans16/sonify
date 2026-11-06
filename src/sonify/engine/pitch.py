"""Note-block style pitch shifting (resampling: pitch and duration change together)."""

from __future__ import annotations

import numpy as np


def semitone_ratio(semitones: float) -> float:
    return 2.0 ** (semitones / 12.0)


def shift(samples: np.ndarray, semitones: float) -> np.ndarray:
    """Return ``samples`` (int16, frames x channels) played ``semitones`` higher."""
    if semitones == 0 or len(samples) == 0:
        return samples
    ratio = semitone_ratio(semitones)
    new_len = max(1, int(len(samples) / ratio))
    positions = np.arange(new_len) * ratio
    base = np.arange(len(samples))
    out = np.stack(
        [np.interp(positions, base, samples[:, ch].astype(np.float32)) for ch in range(samples.shape[1])],
        axis=1,
    )
    return np.clip(out, -32768, 32767).astype(np.int16)
