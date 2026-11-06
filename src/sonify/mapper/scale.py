"""Musical scales and note helpers for pitched sounds."""

from __future__ import annotations

import re
from typing import Dict, Sequence, Tuple

#: Semitone offsets within one octave, starting from the root.
SCALES: Dict[str, Tuple[int, ...]] = {
    "pentatonic_minor": (0, 3, 5, 7, 10),
    "pentatonic_major": (0, 2, 4, 7, 9),
}

_NOTE_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")
_NATURALS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def scale_intervals(name: str) -> Tuple[int, ...]:
    try:
        return SCALES[name]
    except KeyError:
        raise ValueError(f"unknown scale '{name}' (known: {', '.join(sorted(SCALES))})") from None


def note_to_midi(name: str) -> int:
    """``"D3"`` -> 50 (middle C is C4 = 60)."""
    match = _NOTE_RE.match(name.strip())
    if not match:
        raise ValueError(f"'{name}' is not a note name like D3, F#4 or Bb2")
    letter, accidental, octave = match.groups()
    semitone = _NATURALS[letter.upper()] + {"#": 1, "b": -1, "": 0}[accidental]
    return 12 * (int(octave) + 1) + semitone


def quantize_to_scale(
    value: float,
    lo: float,
    hi: float,
    intervals: Sequence[int],
    octaves: int,
) -> int:
    """Map ``value`` in ``[lo, hi]`` to a semitone offset above the root that
    is always a member of the scale.

    TODO(you): implement this. Everything pitched goes through here, which is
    what stops the soundscape from ever sounding random.

    Suggested approach:
      1. Normalise: ``t = (value - lo) / (hi - lo)`` and clamp it to [0, 1]
         (guard ``hi == lo``; reversed ranges where ``lo > hi`` should work).
      2. Count the scale degrees available: ``len(intervals) * octaves + 1``
         (the +1 lets ``t == 1`` land exactly on the top root).
      3. Pick a degree index: ``round(t * (degrees - 1))``.
      4. Split the index into ``octave, step = divmod(index, len(intervals))``
         and return ``12 * octave + intervals[step]``.

    Contract (see tests/test_scale.py): the result is 0 at ``lo``, rises
    monotonically with ``value``, never leaves ``0 .. 12 * octaves``, and
    ``result % 12`` is always in ``intervals``.
    """
    raise NotImplementedError("quantize_to_scale is yours to implement (see docstring)")
