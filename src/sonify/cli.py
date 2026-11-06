"""Command line interface: setup, run, test, list."""

from __future__ import annotations

import logging
import socket
import time
from pathlib import Path
from typing import Optional

import click

from . import __version__
from .assets.installer import run_setup
from .assets.locate import AssetError, find_assets_dir
from .assets.resolve import load_index
from .bus import EventBus
from .config import Config, ConfigFileError, load_config
from .daemon import Daemon
from .engine import Engine, MissingAssetsError, SoundBank
from .engine.backend import AudioUnavailableError, PygameBackend
from .mapper import Mapper, referenced_sounds, root_pitch
from .models import AmbientUpdate, SoundEvent
from .sources import unknown_signals

config_option = click.option(
    "--config", "config_path", type=click.Path(path_type=Path), default="config.yaml",
    show_default=True, help="Path to the YAML config.",
)
sounds_option = click.option(
    "--sounds-dir", type=click.Path(path_type=Path), default="sounds",
    show_default=True, help="Folder written by `sonify setup`.",
)


def _backend() -> PygameBackend:
    try:
        return PygameBackend()
    except AudioUnavailableError as exc:
        raise click.ClickException(str(exc))


def _load(config_path: Path) -> Config:
    try:
        return load_config(config_path)
    except ConfigFileError as exc:
        raise click.ClickException(str(exc))


@click.group()
@click.version_option(__version__)
@click.option("-v", "--verbose", is_flag=True, help="Log what the daemon is doing.")
def main(verbose: bool) -> None:
    """Hear the health of your machines as Minecraft ambience."""
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


@main.command()
@config_option
@sounds_option
@click.option("--minecraft-dir", type=click.Path(path_type=Path), help="Minecraft assets folder.")
@click.option("--index", "index_name", help="Asset index name (default: newest with sounds).")
@click.option("--force", is_flag=True, help="Re-extract sounds that already exist.")
def setup(config_path: Path, sounds_dir: Path, minecraft_dir: Optional[Path], index_name: Optional[str], force: bool) -> None:
    """Extract and convert the sounds named in the config from your Minecraft install."""
    config = _load(config_path)
    try:
        assets_dir = find_assets_dir(minecraft_dir)
        index = load_index(assets_dir, index_name)
    except AssetError as exc:
        raise click.ClickException(str(exc))
    click.echo(f"Using {assets_dir} (index {index.name})")
    result = run_setup(config, index, sounds_dir, force=force, progress=click.echo)
    click.echo(f"\n{len(result.installed)} sound(s) ready in {sounds_dir}/")
    if result.failed:
        raise click.ClickException(
            f"{len(result.failed)} sound(s) could not be set up: {', '.join(result.failed)}. "
            "Fix their `key` in the config and re-run."
        )


@main.command()
@config_option
@sounds_option
@click.option("--volume", type=click.FloatRange(0, 1), help="Master volume 0-1 (overrides the config).")
@click.option("--mute", is_flag=True, help="Start muted.")
@click.option("--ui", is_flag=True, help="Serve the dashboard on 127.0.0.1.")
@click.option("--port", type=click.IntRange(1, 65535), default=8765, show_default=True, help="Dashboard port (with --ui).")
def run(config_path: Path, sounds_dir: Path, volume: Optional[float], mute: bool, ui: bool, port: int) -> None:
    """Start the daemon."""
    config = _load(config_path)
    bank = SoundBank(sounds_dir)
    try:
        bank.require(referenced_sounds(config))
    except MissingAssetsError as exc:
        raise click.ClickException(str(exc))
    for name in unknown_signals(config):
        click.echo(f"warning: signal '{name}' has no source and will never fire", err=True)
    if ui:
        _require_free_port(port)

    bus = EventBus()
    engine = Engine(config, bank, _backend(), bus)
    if volume is not None:
        engine.set_master_volume(volume)
    engine.set_muted(mute)
    daemon = Daemon(config, engine, Mapper(config, bus), bus)
    dashboard = None
    if ui:
        from .ui.server import DashboardServer, create_app

        dashboard = DashboardServer(create_app(daemon, config_path, port), port)
        dashboard.start()
        click.echo(f"Dashboard: {dashboard.url}")
    click.echo("sonify running. Ctrl-C to stop." + (" (muted)" if mute else ""))
    try:
        daemon.run()
    except KeyboardInterrupt:
        daemon.stop()
        click.echo("\nbye")
    finally:
        if dashboard is not None:
            dashboard.stop()


def _require_free_port(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise click.ClickException(f"Cannot use port {port} for the dashboard: {exc}. Try --port.")


@main.command()
@click.argument("sound")
@config_option
@sounds_option
@click.option("--pitch", type=int, help="Semitones from the sample's native pitch (pitched sounds).")
@click.option("--volume", type=click.FloatRange(0, 1), help="Master volume 0-1.")
def test(sound: str, config_path: Path, sounds_dir: Path, pitch: Optional[int], volume: Optional[float]) -> None:
    """Play one configured sound so you can tune the config."""
    config = _load(config_path)
    if sound not in config.sounds:
        raise click.ClickException(
            f"Unknown sound '{sound}'. Defined sounds: {', '.join(config.sounds) or 'none'}"
        )
    bank = SoundBank(sounds_dir)
    try:
        bank.require([sound])
    except MissingAssetsError as exc:
        raise click.ClickException(str(exc))

    engine = Engine(config, bank, _backend())
    if volume is not None:
        engine.set_master_volume(volume)
    kind = config.sounds[sound].kind
    if kind == "loop":
        engine.set_ambient(AmbientUpdate(sound, 1.0))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            engine.tick()
            time.sleep(0.05)
    else:
        if kind == "pitched" and pitch is None:
            pitch = root_pitch(config)
        engine.play(SoundEvent(sound=sound, signal="test", value=0.0, pitch=pitch), force=True)
        deadline = time.monotonic() + 8
        time.sleep(0.1)
        while engine.state()["active"] and time.monotonic() < deadline:
            time.sleep(0.05)
    engine.close()


@main.command(name="list")
@config_option
@sounds_option
def list_cmd(config_path: Path, sounds_dir: Path) -> None:
    """Show available sounds and the current mappings."""
    config = _load(config_path)
    have = set(SoundBank(sounds_dir).available())
    click.echo("Sounds:")
    for sound_id, sdef in config.sounds.items():
        status = "ok" if sound_id in have else "missing (run `sonify setup`)"
        click.echo(f"  {sound_id:<16} {sdef.kind:<8} {sdef.key:<28} {status}")
    click.echo("\nMappings:")
    for row in Mapper(config).describe():
        click.echo(f"  {row['signal']:<16} -> {row['sound']:<16} {row['rule']}")
    for name in config.ambient_baseline:
        click.echo(f"  {'(baseline)':<16} -> {name.sound:<16} always on, gain {name.gain:g}")
    for name in unknown_signals(config):
        click.echo(f"\nwarning: signal '{name}' has no source", err=True)
