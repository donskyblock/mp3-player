from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


APP_DIR_NAME = "SabrinthPlayer"
DEFAULT_SETTINGS: Dict[str, Any] = {
    "theme": "pitch_black",
    "shuffle_on_load": True,
    "autoplay_on_load": True,
    "recursive_scan": True,
    "default_volume": 58,
    "ui_scale_percent": 100,
    "use_default_download_dir": True,
    "download_dir": "",
    "show_track_stats": True,
    "auto_adjust_enabled": False,
    "enable_global_hotkeys": False,
    "keybind_play_pause": "Space",
    "keybind_next": "Ctrl+Right",
    "keybind_prev": "Ctrl+Left",
    "keybind_volume_up": "Ctrl+Up",
    "keybind_volume_down": "Ctrl+Down",
    "keybind_open_settings": "Ctrl+,",
    "keybind_find_songs": "Ctrl+K",
    "keybind_open_debug": "Ctrl+Shift+D",
    "keybind_quit": "Ctrl+Q",
    "spotify_client_id": "",
    "spotify_client_secret": "",
}


def _system_app_dir() -> Path:
    if os.name == "nt":
        base = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_DIR_NAME
    if os.uname().sysname.lower() == "darwin":  # type: ignore[attr-defined]
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    return Path.home() / ".local" / "share" / APP_DIR_NAME


def resolve_app_dir() -> Path:
    primary = _system_app_dir()
    try:
        primary.mkdir(parents=True, exist_ok=True)
        probe = primary / ".write_probe.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return primary
    except OSError:
        fallback = Path.cwd() / ".sabrinth-player"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


class SettingsManager:
    def __init__(self) -> None:
        self.app_dir = resolve_app_dir()
        self.path = self.app_dir / "settings.json"

        self.data = DEFAULT_SETTINGS.copy()
        loaded = self._load()
        if loaded:
            self.data.update(loaded)

        if not str(self.data.get("download_dir", "")).strip():
            self.data["download_dir"] = str(self.app_dir / "downloads")
        self.save()

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def update(self, values: Dict[str, Any]) -> None:
        self.data.update(values)
        self.save()

    def get_bool(self, key: str) -> bool:
        return bool(self.data.get(key, DEFAULT_SETTINGS.get(key, False)))

    def get_int(self, key: str) -> int:
        fallback = int(DEFAULT_SETTINGS.get(key, 0))
        try:
            return int(self.data.get(key, fallback))
        except (TypeError, ValueError):
            return fallback

    def get_str(self, key: str) -> str:
        fallback = str(DEFAULT_SETTINGS.get(key, ""))
        return str(self.data.get(key, fallback))

    def download_dir(self) -> Path:
        path = Path(self.get_str("download_dir")).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def imports_dir(self) -> Path:
        path = self.app_dir / "imports"
        path.mkdir(parents=True, exist_ok=True)
        return path
