from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from sonify.cli import main

CONFIG = {
    "sounds": {"hiss": {"key": "entity.creeper.primed"}},
    "signals": {"net_errors": {"events": [{"sound": "hiss", "when": {"above": 1}, "cooldown_s": 5}]}},
}


def write_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(CONFIG))
    return path


def test_list_shows_missing_sounds(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["list", "--config", str(write_config(tmp_path)), "--sounds-dir", str(tmp_path / "s")])
    assert result.exit_code == 0
    assert "missing" in result.output and "net_errors" in result.output


def test_run_without_sounds_explains_setup(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["run", "--config", str(write_config(tmp_path)), "--sounds-dir", str(tmp_path / "s")])
    assert result.exit_code == 1
    assert "sonify setup" in result.output


def test_missing_config_message(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["list", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 1 and "Config file not found" in result.output


def test_invalid_config_lists_paths(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("master_volume: 7\n")
    result = CliRunner().invoke(main, ["list", "--config", str(bad)])
    assert result.exit_code == 1 and "master_volume" in result.output


def test_setup_without_minecraft(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main, ["setup", "--config", str(write_config(tmp_path)), "--minecraft-dir", str(tmp_path / "none")]
    )
    assert result.exit_code == 1 and "Minecraft assets folder not found" in result.output


def test_setup_end_to_end_with_fake_install(tmp_path: Path, fake_minecraft: Path) -> None:
    out = tmp_path / "sounds"
    result = CliRunner().invoke(
        main,
        ["setup", "--config", str(write_config(tmp_path)), "--minecraft-dir", str(fake_minecraft), "--sounds-dir", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert (out / "hiss" / "1.wav").is_file()


def test_test_command_rejects_unknown_sound(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["test", "nope", "--config", str(write_config(tmp_path))])
    assert result.exit_code == 1 and "Defined sounds: hiss" in result.output


def test_missing_mixer_gives_actionable_error(tmp_path: Path, monkeypatch) -> None:
    import sys
    import types

    # Simulate pygame built without a mixer (e.g. plain `pygame` on a new Python).
    class NoMixer(types.ModuleType):
        error = Exception

        def __getattr__(self, name: str):
            raise NotImplementedError("mixer module not available")

    monkeypatch.setitem(sys.modules, "pygame", NoMixer("pygame"))
    sounds = tmp_path / "sounds" / "hiss"
    sounds.mkdir(parents=True)
    import numpy as np
    import soundfile as sf

    tone = np.zeros(100, dtype=np.float32)
    sf.write(str(sounds / "1.wav"), np.stack([tone, tone], axis=1), 44100)
    result = CliRunner().invoke(
        main, ["run", "--config", str(write_config(tmp_path)), "--sounds-dir", str(tmp_path / "sounds")]
    )
    assert result.exit_code == 1
    assert "pip install pygame-ce" in result.output


def test_init_writes_a_valid_starter_config(tmp_path: Path) -> None:
    target = tmp_path / "config.yaml"
    result = CliRunner().invoke(main, ["init", "--config", str(target)])
    assert result.exit_code == 0
    listed = CliRunner().invoke(main, ["list", "--config", str(target), "--sounds-dir", str(tmp_path / "s")])
    assert listed.exit_code == 0 and "cpu_percent" in listed.output


def test_init_refuses_to_overwrite(tmp_path: Path) -> None:
    target = write_config(tmp_path)
    result = CliRunner().invoke(main, ["init", "--config", str(target)])
    assert result.exit_code == 1 and "--force" in result.output
    assert CliRunner().invoke(main, ["init", "--config", str(target), "--force"]).exit_code == 0


def test_packaged_default_matches_repo_config() -> None:
    repo = Path(__file__).resolve().parents[1] / "config.yaml"
    packaged = Path(__file__).resolve().parents[1] / "src" / "sonify" / "default_config.yaml"
    assert repo.read_text() == packaged.read_text()
