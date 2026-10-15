"""Load ``config/settings.yml`` and resolve its paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS = REPO_ROOT / "config" / "settings.yml"

# setting key -> environment variable that overrides it
_PATH_OVERRIDES = {
    ("paths", "data_dir"): "MDG_DATA_DIR",
    ("paths", "cache_dir"): "MDG_CACHE_DIR",
    ("paths", "basins_dir"): "MDG_BASINS_DIR",
    ("paths", "models_dir"): "MDG_MODELS_DIR",
    ("local_inputs", "hydrobasins"): "MDG_HYDROBASINS",
    ("local_inputs", "gpm_daily"): "MDG_GPM_DAILY",
}


@dataclass(frozen=True)
class Settings:
    """Parsed settings. Section dicts are kept as-is; paths are resolved to absolute."""

    source: Path
    raw: Dict[str, Any]
    data_dir: Path
    cache_dir: Path
    basins_dir: Path
    models_dir: Path
    hydrobasins: Path
    gpm_daily: Path

    def section(self, name: str) -> Dict[str, Any]:
        return self.raw.get(name, {})

    @property
    def domain(self) -> Dict[str, Any]:
        return self.section("domain")

    @property
    def static_data(self) -> Dict[str, Any]:
        return self.section("static_data")

    @property
    def rainfall(self) -> Dict[str, Any]:
        return self.section("rainfall")

    @property
    def model(self) -> Dict[str, Any]:
        return self.section("model")

    @property
    def http(self) -> Dict[str, Any]:
        return self.section("http")

    def basin_dir(self, basin_id: str) -> Path:
        return self.basins_dir / basin_id

    def model_dir(self, basin_id: str) -> Path:
        return self.models_dir / basin_id


def _resolve(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def load_settings(path: Optional[Path] = None) -> Settings:
    """Read the settings file (default ``config/settings.yml``), applying env-var overrides."""
    source = Path(path) if path else DEFAULT_SETTINGS
    raw = yaml.safe_load(source.read_text()) or {}

    resolved = {}
    for (section, key), env in _PATH_OVERRIDES.items():
        value = os.environ.get(env) or raw.get(section, {}).get(key)
        if value is None:
            raise KeyError(f"{section}.{key} missing from {source} (or set {env})")
        resolved[key] = _resolve(value)

    return Settings(source=source.resolve(), raw=raw, **resolved)
