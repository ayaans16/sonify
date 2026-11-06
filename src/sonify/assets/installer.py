"""`sonify setup`: copy the sounds named in the config into ./sounds/."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..config import Config
from .convert import convert_to_wav
from .locate import AssetError
from .resolve import AssetIndex

MANIFEST = "manifest.json"


@dataclass
class SetupResult:
    installed: Dict[str, List[Path]] = field(default_factory=dict)
    failed: Dict[str, str] = field(default_factory=dict)


def run_setup(
    config: Config,
    index: AssetIndex,
    out_dir: Path,
    force: bool = False,
    max_variants: int = 4,
    progress: Optional[Callable[[str], None]] = None,
) -> SetupResult:
    """Resolve and convert every sound in ``config.sounds``.

    A sound that cannot be resolved is recorded in ``failed`` and skipped so
    one bad key does not block the rest.
    """
    say = progress or (lambda _msg: None)
    result = SetupResult()
    out_dir.mkdir(parents=True, exist_ok=True)

    for sound_id, sound in config.sounds.items():
        target = out_dir / sound_id
        existing = sorted(target.glob("*.wav")) if target.is_dir() else []
        if existing and not force:
            say(f"  {sound_id}: already present ({len(existing)} files), skipping")
            result.installed[sound_id] = existing
            continue
        try:
            sources = index.resolve(sound.key)[:max_variants]
            if target.is_dir():
                shutil.rmtree(target)
            files = []
            for n, src in enumerate(sources, start=1):
                dst = target / f"{n}.wav"
                convert_to_wav(src, dst)
                files.append(dst)
        except AssetError as exc:
            result.failed[sound_id] = str(exc)
            say(f"  {sound_id}: FAILED - {exc}")
            continue
        result.installed[sound_id] = files
        say(f"  {sound_id}: {sound.key} -> {len(files)} file(s)")

    _write_manifest(config, result, out_dir, index.name)
    return result


def _write_manifest(config: Config, result: SetupResult, out_dir: Path, index_name: str) -> None:
    manifest = {
        "index": index_name,
        "sounds": {
            sound_id: {"key": config.sounds[sound_id].key, "files": [p.name for p in files]}
            for sound_id, files in result.installed.items()
        },
    }
    (out_dir / MANIFEST).write_text(json.dumps(manifest, indent=2))
