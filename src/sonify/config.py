"""Config schema, loading and (atomic) saving."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SoundDef(_Model):
    #: Minecraft sound event (e.g. ``entity.creeper.primed``) or a direct
    #: path under minecraft/sounds (e.g. ``mob/creeper/say1``).
    key: str
    kind: Literal["loop", "oneshot", "pitched"] = "oneshot"
    volume: float = Field(1.0, ge=0, le=1)
    #: Engine-level minimum gap between plays of this sound.
    cooldown_s: float = Field(0.05, ge=0)


class DuckingCfg(_Model):
    enabled: bool = True
    window_s: float = Field(5.0, gt=0)
    max_reduction_db: float = Field(9.0, ge=0)
    #: Plays per second at which a sound is ducked by the full amount.
    full_duck_rate: float = Field(2.0, gt=0)


class PitchedCfg(_Model):
    scale: str = "pentatonic_minor"
    root: str = "D3"
    range_octaves: int = Field(2, ge=1, le=4)


class Range(_Model):
    from_: float = Field(alias="from")
    to: float


class Gain(_Model):
    """Linear map of a signal value onto an ambient gain."""

    min_value: float = 0.0
    max_value: float = 100.0
    min_gain: float = Field(0.0, alias="min", ge=0, le=1)
    max_gain: float = Field(1.0, alias="max", ge=0, le=1)


class When(_Model):
    above: Optional[float] = None
    below: Optional[float] = None
    hysteresis: float = Field(0.0, ge=0)


class AmbientRule(_Model):
    sound: str
    gain: Optional[Gain] = None


class EventRule(_Model):
    sound: str
    mode: Literal["threshold", "pitch_tempo"] = "threshold"
    when: Optional[When] = None
    #: pitch_tempo only: value range mapped onto the scale.
    pitch: Optional[Range] = None
    #: pitch_tempo only: seconds between notes at pitch.from / pitch.to.
    interval_s: Optional[Range] = None
    #: threshold: repeat period while the condition holds.
    cooldown_s: float = Field(0.0, ge=0)
    volume: float = Field(1.0, ge=0, le=1)


class Signal(_Model):
    source: Optional[str] = None
    ambient: Optional[AmbientRule] = None
    events: List[EventRule] = Field(default_factory=list)


class BaselineAmbient(_Model):
    sound: str
    gain: float = Field(1.0, ge=0, le=1)


class Config(_Model):
    version: int = 1
    master_volume: float = Field(0.7, ge=0, le=1)
    polyphony: int = Field(16, ge=1, le=64)
    max_events_per_s: float = Field(8.0, gt=0)
    ducking: DuckingCfg = Field(default_factory=DuckingCfg)
    sounds: Dict[str, SoundDef] = Field(default_factory=dict)
    pitched: PitchedCfg = Field(default_factory=PitchedCfg)
    signals: Dict[str, Signal] = Field(default_factory=dict)
    ambient_baseline: List[BaselineAmbient] = Field(default_factory=list)

    def to_plain(self) -> Dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True)


class ConfigFileError(Exception):
    """The config file is missing, unreadable or invalid."""


@dataclass(frozen=True)
class ConfigError:
    path: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        return {"path": self.path, "message": self.message}


def schema_errors(raw: Any) -> List[ConfigError]:
    """Errors from the structural (type/range/unknown-key) schema only."""
    try:
        Config.model_validate(raw)
    except ValidationError as exc:
        return [
            ConfigError(".".join(str(p) for p in err["loc"]), err["msg"])
            for err in exc.errors()
        ]
    return []


def validate_mapping(raw: Any) -> List[ConfigError]:
    """Validate a raw config dict; returns an empty list when it is valid.

    This is what the dashboard's mapping editor (``PUT /config``) calls
    before anything is written to disk.

    TODO(you): implement the cross-field and referential rules that pydantic
    cannot express. The schema needs to enforce:

      * every ``sound`` in ``ambient``, ``events`` and ``ambient_baseline``
        references an id defined under ``sounds``;
      * ``cooldown_s >= 0``; for ``pitch_tempo`` rules ``interval_s`` must
        satisfy ``from > 0`` and ``to > 0``;
      * ``above`` / ``below`` thresholds are numbers and, when both are set,
        ``below < above``; ``hysteresis`` is smaller than the span it guards;
      * ``pitch_tempo`` rules reference a ``kind: pitched`` sound and provide
        both ``pitch`` and ``interval_s``; ``threshold`` rules provide
        ``when`` with at least one of ``above`` / ``below``;
      * ``pitched.scale`` is a known scale name and ``pitched.root`` parses
        as a note name such as ``D3`` (see ``sonify.mapper.scale``);
      * ``ambient`` sounds are ``kind: loop``.

    Return ``ConfigError(path, message)`` items with dotted paths such as
    ``signals.cpu_percent.events.0.cooldown_s`` so the editor can show each
    message inline. For now only the structural checks run.
    """
    return schema_errors(raw)


def parse_config(raw: Any) -> Config:
    return Config.model_validate(raw)


def load_config(path: Path) -> Config:
    path = Path(path)
    if not path.is_file():
        raise ConfigFileError(
            f"Config file not found: {path}\n"
            "Pass --config <file>, or run from the directory that holds config.yaml."
        )
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigFileError(f"{path} is not valid YAML: {exc}") from exc
    errors = validate_mapping(raw if raw is not None else {})
    if errors:
        lines = "\n".join(f"  {e.path or '<root>'}: {e.message}" for e in errors)
        raise ConfigFileError(f"{path} is invalid:\n{lines}")
    return parse_config(raw if raw is not None else {})


def save_config(config: Config, path: Path) -> None:
    """Write ``config`` to ``path`` atomically (temp file, then rename)."""
    path = Path(path)
    text = yaml.safe_dump(config.to_plain(), sort_keys=False, default_flow_style=False)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
