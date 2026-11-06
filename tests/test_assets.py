from __future__ import annotations

from pathlib import Path

import pytest
import soundfile as sf

from sonify.assets.convert import SAMPLE_RATE
from sonify.assets.installer import run_setup
from sonify.assets.locate import AssetError, MinecraftNotFoundError, find_assets_dir
from sonify.assets.resolve import SoundNotFoundError, load_index
from sonify.config import parse_config


def test_missing_install_has_helpful_message(tmp_path: Path) -> None:
    with pytest.raises(MinecraftNotFoundError) as exc:
        find_assets_dir(tmp_path / "nope")
    assert "--minecraft-dir" in str(exc.value)


def test_dir_without_indexes_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(MinecraftNotFoundError, match="missing: indexes, objects"):
        find_assets_dir(tmp_path)


def test_resolves_event_direct_path_and_event_alias(fake_minecraft: Path) -> None:
    index = load_index(find_assets_dir(fake_minecraft))
    assert len(index.resolve("entity.creeper.primed")) == 2
    assert len(index.resolve("mob/creeper/say1")) == 1  # direct path fallback
    assert len(index.resolve("alias.event")) == 2  # type: event indirection


def test_unknown_sound_suggests_close_match(fake_minecraft: Path) -> None:
    index = load_index(fake_minecraft)
    with pytest.raises(SoundNotFoundError, match="entity.creeper.primed"):
        index.resolve("entity.creeper.primd")


def test_unknown_index_name_lists_available(fake_minecraft: Path) -> None:
    with pytest.raises(AssetError, match="Available: 17"):
        load_index(fake_minecraft, "99")


def test_setup_converts_to_stereo_wav_and_reports_failures(
    fake_minecraft: Path, tmp_path: Path
) -> None:
    config = parse_config(
        {
            "sounds": {
                "hiss": {"key": "entity.creeper.primed"},
                "harp": {"key": "block.note_block.harp", "kind": "pitched"},
                "ghost": {"key": "does.not.exist"},
            }
        }
    )
    out = tmp_path / "sounds"
    result = run_setup(config, load_index(fake_minecraft), out)

    assert set(result.installed) == {"hiss", "harp"}
    assert "ghost" in result.failed
    data, rate = sf.read(str(out / "hiss" / "1.wav"))
    assert rate == SAMPLE_RATE and data.ndim == 2 and data.shape[1] == 2
    assert (out / "manifest.json").is_file()

    # Re-running without --force leaves existing files alone.
    again = run_setup(config, load_index(fake_minecraft), out)
    assert set(again.installed) == {"hiss", "harp"}
