"""Alkalmazásállapot (utolsó mappák, beállítások, saját presetek) mentése."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import APP_ID
from .settings import ConversionSettings, SourceOptions, from_dict, to_dict

SETTINGS_FILE = "settings.json"
PORTABLE_MARKER = "portable.txt"


def app_dir() -> Path:
    """A futtatható állomány (exe) mappája, illetve fejlesztéskor a projekt gyökere."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def config_dir() -> Path:
    """Hordozható módban (``portable.txt`` az exe mellett) a beállítások az
    exe mellé kerülnek, egyébként a felhasználói profilba."""
    override = os.environ.get("WEBKEP_CONFIG_DIR")
    if override:
        return Path(override)
    if (app_dir() / PORTABLE_MARKER).exists():
        return app_dir() / "settings"
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_ID


@dataclass
class AppState:
    input_dir: str = ""
    output_dir: str = ""
    conversion: ConversionSettings = field(default_factory=ConversionSettings)
    source: SourceOptions = field(default_factory=SourceOptions)
    workers: int = 0
    language: str = "hu"
    theme: str = "dark"
    open_output_when_done: bool = False
    notify_when_done: bool = True
    user_presets: dict[str, dict] = field(default_factory=dict)
    last_preset: str = "balanced"
    window_geometry: str = ""
    window_state: str = ""
    splitter_state: str = ""
    recent_inputs: list[str] = field(default_factory=list)
    recent_outputs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppState":
        state = from_dict(cls, data)
        state.conversion.validate()
        state.source.validate()
        if state.language not in ("hu", "en"):
            state.language = "hu"
        if state.theme not in ("dark", "light"):
            state.theme = "dark"
        state.workers = max(0, min(64, state.workers))
        return state

    def remember(self, attr: str, value: str, limit: int = 8) -> None:
        items: list[str] = getattr(self, attr)
        if not value:
            return
        items[:] = [value] + [v for v in items if os.path.normcase(v) != os.path.normcase(value)]
        del items[limit:]


def load_state(path: Path | None = None) -> AppState:
    path = path or config_dir() / SETTINGS_FILE
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return AppState.from_dict(data)
    except (OSError, ValueError):
        pass
    return AppState()


def save_state(state: AppState, path: Path | None = None) -> bool:
    path = path or config_dir() / SETTINGS_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state.to_dict(), fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False
