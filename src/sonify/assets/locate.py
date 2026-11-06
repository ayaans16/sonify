"""Find the user's Minecraft assets directory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

DEFAULT_ASSETS_DIR = Path.home() / "Library" / "Application Support" / "minecraft" / "assets"
ENV_VAR = "SONIFY_MINECRAFT_ASSETS"


class AssetError(Exception):
    """Base class for asset problems; messages are meant for end users."""


class MinecraftNotFoundError(AssetError):
    pass


def find_assets_dir(override: Optional[Path] = None) -> Path:
    """Return a validated assets dir (one containing indexes/ and objects/)."""
    if override is not None:
        candidate, origin = Path(override).expanduser(), "--minecraft-dir"
    elif os.environ.get(ENV_VAR):
        candidate, origin = Path(os.environ[ENV_VAR]).expanduser(), f"${ENV_VAR}"
    else:
        candidate, origin = DEFAULT_ASSETS_DIR, "default location"

    if not candidate.is_dir():
        raise MinecraftNotFoundError(
            f"Minecraft assets folder not found at {candidate} ({origin}).\n"
            "Install Minecraft Java Edition and launch it once so it downloads "
            "its assets, or point sonify at the folder with --minecraft-dir."
        )
    missing = [name for name in ("indexes", "objects") if not (candidate / name).is_dir()]
    if missing:
        raise MinecraftNotFoundError(
            f"{candidate} does not look like a Minecraft assets folder "
            f"(missing: {', '.join(missing)}).\n"
            "Launch the game once so the launcher downloads its assets."
        )
    return candidate
