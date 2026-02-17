from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}


@dataclass
class SongStats:
    played: int = 0
    started: int = 0
    skipped: int = 0


class PlaylistManager:
    def __init__(self) -> None:
        self.playlist: List[Path] = []
        self.filtered_playlist: List[Path] = []
        self.index = 0

        self._app_dir = self._resolve_app_dir()
        self._app_dir.mkdir(parents=True, exist_ok=True)
        self._stats_path = self._app_dir / "stats.json"
        self.song_stats: Dict[str, Dict[str, int]] = self._load_stats()

    @staticmethod
    def _resolve_app_dir() -> Path:
        if os.name == "nt":
            base = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
            return base / "PythonMP3Player"
        if os.uname().sysname.lower() == "darwin":  # type: ignore[attr-defined]
            return Path.home() / "Library" / "Application Support" / "PythonMP3Player"
        return Path.home() / ".local" / "share" / "PythonMP3Player"

    def _load_stats(self) -> Dict[str, Dict[str, int]]:
        if not self._stats_path.exists():
            return {}
        try:
            return json.loads(self._stats_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_stats(self) -> None:
        self._stats_path.write_text(json.dumps(self.song_stats, indent=2), encoding="utf-8")

    def update_stat(self, song_name: str, key: str) -> None:
        entry = self.song_stats.setdefault(song_name, {"played": 0, "started": 0, "skipped": 0})
        if key in entry:
            entry[key] += 1
            self.save_stats()

    def load_folder(self, folder_path: Path, shuffle: bool = True) -> None:
        if not folder_path.exists() or not folder_path.is_dir():
            return
        songs = [
            p
            for p in folder_path.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        if shuffle:
            random.shuffle(songs)
        else:
            songs.sort()
        self.playlist = songs
        self.filtered_playlist = songs.copy()
        self.index = 0

    def set_playlist(self, songs: List[Path], shuffle: bool = False) -> None:
        cleaned = [p for p in songs if p.exists() and p.suffix.lower() in SUPPORTED_EXTENSIONS]
        if shuffle:
            random.shuffle(cleaned)
        self.playlist = cleaned
        self.filtered_playlist = cleaned.copy()
        self.index = 0

    def apply_search(self, query: str) -> List[Path]:
        query = query.strip().lower()
        if not query:
            self.filtered_playlist = self.playlist.copy()
        else:
            self.filtered_playlist = [p for p in self.playlist if query in p.name.lower()]
        return self.filtered_playlist

    def stats_for(self, song: Path) -> SongStats:
        data = self.song_stats.get(song.name, {"played": 0, "started": 0, "skipped": 0})
        return SongStats(**data)

    def next_index(self) -> int:
        if not self.playlist:
            return 0
        self.index = (self.index + 1) % len(self.playlist)
        return self.index

    def prev_index(self) -> int:
        if not self.playlist:
            return 0
        self.index = (self.index - 1) % len(self.playlist)
        return self.index
