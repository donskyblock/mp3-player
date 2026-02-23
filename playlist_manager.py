from __future__ import annotations

import json
import os
import hashlib
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}
LCG_MULTIPLIER = 6364136223846793005
LCG_INCREMENT = 1442695040888963407


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
        self.search_query = ""
        self.shuffle_seed: str | None = None

        self._app_dir = self._resolve_app_dir()
        self._app_dir.mkdir(parents=True, exist_ok=True)
        self._stats_path = self._app_dir / "stats.json"
        self.song_stats: Dict[str, Dict[str, int]] = self._load_stats()

    @staticmethod
    def _playlist_sort_key(song: Path) -> str:
        return str(song).lower()

    @staticmethod
    def _normalize_seed(seed: str | int | None) -> str:
        if seed is None:
            return str(secrets.randbits(64))
        seed_text = str(seed).strip()
        if seed_text:
            return seed_text
        return str(secrets.randbits(64))

    @staticmethod
    def _seed_to_state(seed: str) -> int:
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        state = int.from_bytes(digest[:8], byteorder="big")
        return state if state != 0 else 1

    @staticmethod
    def _next_state(state: int) -> int:
        return (state * LCG_MULTIPLIER + LCG_INCREMENT) & ((1 << 64) - 1)

    @classmethod
    def _seeded_shuffle(cls, songs: List[Path], seed: str) -> List[Path]:
        shuffled = songs.copy()
        if len(shuffled) < 2:
            return shuffled

        state = cls._seed_to_state(seed)
        for i in range(len(shuffled) - 1, 0, -1):
            state = cls._next_state(state)
            j = state % (i + 1)
            shuffled[i], shuffled[j] = shuffled[j], shuffled[i]
        return shuffled

    def _sync_filtered_playlist(self) -> None:
        if not self.search_query:
            self.filtered_playlist = self.playlist.copy()
            return
        self.filtered_playlist = [p for p in self.playlist if self.search_query in p.name.lower()]

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

    def load_folder(
        self, folder_path: Path, shuffle: bool = True, seed: str | int | None = None
    ) -> str | None:
        if not folder_path.exists() or not folder_path.is_dir():
            return None
        songs = [
            p
            for p in folder_path.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        songs.sort(key=self._playlist_sort_key)
        if shuffle:
            used_seed = self._normalize_seed(seed)
            songs = self._seeded_shuffle(songs, used_seed)
        else:
            used_seed = None
        self.playlist = songs
        self._sync_filtered_playlist()
        self.index = 0
        self.shuffle_seed = used_seed
        return used_seed

    def set_playlist(
        self, songs: List[Path], shuffle: bool = False, seed: str | int | None = None
    ) -> str | None:
        cleaned = [p for p in songs if p.exists() and p.suffix.lower() in SUPPORTED_EXTENSIONS]
        if shuffle:
            used_seed = self._normalize_seed(seed)
            cleaned = self._seeded_shuffle(
                sorted(cleaned, key=self._playlist_sort_key),
                used_seed,
            )
        else:
            used_seed = None
        self.playlist = cleaned
        self._sync_filtered_playlist()
        self.index = 0
        self.shuffle_seed = used_seed
        return used_seed

    def reshuffle(self, seed: str | int | None = None) -> str | None:
        if not self.playlist:
            return None

        used_seed = self._normalize_seed(seed)
        current_song = self.playlist[self.index] if 0 <= self.index < len(self.playlist) else None

        base = sorted(self.playlist, key=self._playlist_sort_key)
        self.playlist = self._seeded_shuffle(base, used_seed)
        self.shuffle_seed = used_seed

        if current_song and current_song in self.playlist:
            self.index = self.playlist.index(current_song)
        else:
            self.index = 0
        self._sync_filtered_playlist()
        return used_seed

    def apply_search(self, query: str) -> List[Path]:
        self.search_query = query.strip().lower()
        self._sync_filtered_playlist()
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
