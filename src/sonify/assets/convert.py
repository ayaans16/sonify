"""Convert Minecraft OGG sounds to 44.1 kHz stereo 16-bit WAV."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from .locate import AssetError

SAMPLE_RATE = 44100


def resample(data: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Linear-interpolation resample of a (frames, channels) array."""
    if src_rate == dst_rate or len(data) == 0:
        return data
    new_len = max(1, int(round(len(data) * dst_rate / src_rate)))
    old_t = np.linspace(0.0, 1.0, num=len(data), endpoint=False)
    new_t = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
    return np.stack(
        [np.interp(new_t, old_t, data[:, ch]) for ch in range(data.shape[1])], axis=1
    ).astype(np.float32)


def convert_to_wav(src: Path, dst: Path) -> float:
    """Convert ``src`` to ``dst``; returns the duration in seconds."""
    try:
        data, rate = sf.read(str(src), dtype="float32", always_2d=True)
    except Exception as exc:  # soundfile raises RuntimeError / LibsndfileError
        raise AssetError(f"Could not decode {src.name}: {exc}") from exc
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    data = resample(data, rate, SAMPLE_RATE)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(dst), data, SAMPLE_RATE, subtype="PCM_16")
    return len(data) / SAMPLE_RATE
