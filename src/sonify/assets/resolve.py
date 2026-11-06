"""Resolve Minecraft sound keys to files via indexes/*.json and objects/."""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .locate import AssetError

SOUNDS_JSON = "minecraft/sounds.json"


class SoundNotFoundError(AssetError):
    pass


@dataclass
class AssetIndex:
    assets_dir: Path
    name: str
    objects: Dict[str, Dict[str, Any]]

    def object_path(self, logical_name: str) -> Path:
        digest = self.objects[logical_name]["hash"]
        return self.assets_dir / "objects" / digest[:2] / digest

    def has_file(self, logical_name: str) -> bool:
        return logical_name in self.objects and self.object_path(logical_name).is_file()

    def sound_events(self) -> Dict[str, Any]:
        if not self.has_file(SOUNDS_JSON):
            return {}
        return json.loads(self.object_path(SOUNDS_JSON).read_text())

    def resolve(self, key: str) -> List[Path]:
        """Return the audio files behind a sound event key.

        ``key`` is normally an event from sounds.json (``entity.creeper.primed``).
        If no such event exists it is tried as a direct path under
        ``minecraft/sounds/`` (``mob/creeper/say1``).
        """
        events = self.sound_events()
        if key in events:
            names = _collect_event_sounds(events, key, {key})
        else:
            names = [f"minecraft/sounds/{key}.ogg"]
        files = [self.object_path(n) for n in names if self.has_file(n)]
        if not files:
            hint = difflib.get_close_matches(key, list(events), n=3)
            suggestion = f" Did you mean: {', '.join(hint)}?" if hint else ""
            raise SoundNotFoundError(
                f"No sound files found for '{key}' in index {self.name}.{suggestion}"
            )
        return files


def _collect_event_sounds(events: Dict[str, Any], key: str, seen: Set[str]) -> List[str]:
    names: List[str] = []
    for entry in events[key].get("sounds", []):
        if isinstance(entry, str):
            name, kind = entry, "sound"
        else:
            name, kind = entry["name"], entry.get("type", "sound")
        name = name.split(":", 1)[-1]  # drop a "minecraft:" namespace
        if kind == "event":
            if name in events and name not in seen:
                names.extend(_collect_event_sounds(events, name, seen | {name}))
        else:
            names.append(f"minecraft/sounds/{name}.ogg")
    return names


def load_index(assets_dir: Path, name: Optional[str] = None) -> AssetIndex:
    """Load an asset index; by default the newest one that has sounds.json."""
    index_dir = assets_dir / "indexes"
    if name:
        path = index_dir / (name if name.endswith(".json") else f"{name}.json")
        if not path.is_file():
            available = ", ".join(sorted(p.stem for p in index_dir.glob("*.json"))) or "none"
            raise AssetError(f"Asset index '{name}' not found. Available: {available}")
        return _read_index(path, assets_dir)

    candidates = sorted(index_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise AssetError(
            f"No asset indexes in {index_dir}. Launch Minecraft once so it downloads its assets."
        )
    for path in candidates:
        index = _read_index(path, assets_dir)
        if SOUNDS_JSON in index.objects:
            return index
    raise AssetError(
        f"None of the asset indexes in {index_dir} list {SOUNDS_JSON}. "
        "Launch the game once to finish downloading assets."
    )


def _read_index(path: Path, assets_dir: Path) -> AssetIndex:
    try:
        raw = json.loads(path.read_text())
        objects = raw["objects"]
    except (OSError, ValueError, KeyError) as exc:
        raise AssetError(f"Could not read asset index {path}: {exc}") from exc
    return AssetIndex(assets_dir=assets_dir, name=path.stem, objects=objects)
