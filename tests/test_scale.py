"""Contract for the pentatonic quantizer you implement in mapper/scale.py.

These stay xfail until `quantize_to_scale` is implemented; once it is, remove
the marker (or keep it: non-strict xfail turns into XPASS).
"""

from __future__ import annotations

import pytest

from sonify.mapper.scale import SCALES, note_to_midi, quantize_to_scale, scale_intervals

MINOR = SCALES["pentatonic_minor"]
needs_impl = pytest.mark.xfail(raises=NotImplementedError, reason="TODO: implement quantize_to_scale")


def test_note_names() -> None:
    assert note_to_midi("C4") == 60
    assert note_to_midi("D3") == 50
    assert note_to_midi("F#4") == 66
    assert note_to_midi("Bb2") == 46
    with pytest.raises(ValueError):
        note_to_midi("H9")


def test_unknown_scale() -> None:
    with pytest.raises(ValueError, match="pentatonic_minor"):
        scale_intervals("whole_tone")


@needs_impl
def test_endpoints() -> None:
    assert quantize_to_scale(0, 0, 100, MINOR, 2) == 0
    assert quantize_to_scale(100, 0, 100, MINOR, 2) == 24


@needs_impl
@pytest.mark.parametrize("octaves", [1, 2, 3])
def test_always_in_scale_and_in_range(octaves: int) -> None:
    for v in range(-20, 140):
        note = quantize_to_scale(v, 0, 100, MINOR, octaves)
        assert 0 <= note <= 12 * octaves
        assert note % 12 in MINOR


@needs_impl
def test_monotonic() -> None:
    notes = [quantize_to_scale(v, 0, 100, MINOR, 2) for v in range(0, 101)]
    assert notes == sorted(notes)


@needs_impl
def test_clamps_outside_range_and_degenerate_range() -> None:
    assert quantize_to_scale(-50, 0, 100, MINOR, 2) == 0
    assert quantize_to_scale(500, 0, 100, MINOR, 2) == 24
    assert quantize_to_scale(5, 10, 10, MINOR, 2) == 0
