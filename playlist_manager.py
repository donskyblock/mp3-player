from __future__ import annotations

import json
import hashlib
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from settings_manager import resolve_app_dir


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

        self._app_dir = resolve_app_dir()
        self._app_dir.mkdir(parents=True, exist_ok=True)
        self._stats_path = self._app_dir / "stats.json"
        self._saved_playlists_path = self._app_dir / "saved_playlists.json"
        self.song_stats: Dict[str, Dict[str, int]] = self._load_stats()
        self.saved_playlists: Dict[str, List[str]] = self._load_saved_playlists()

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

    def _load_stats(self) -> Dict[str, Dict[str, int]]:
        if not self._stats_path.exists():
            return {}
        try:
            return json.loads(self._stats_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _load_saved_playlists(self) -> Dict[str, List[str]]:
        if not self._saved_playlists_path.exists():
            return {}
        try:
            value = json.loads(self._saved_playlists_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        if not isinstance(value, dict):
            return {}

        out: Dict[str, List[str]] = {}
        for key, entries in value.items():
            if not isinstance(key, str):
                continue
            if not isinstance(entries, list):
                continue
            paths = [str(p) for p in entries if isinstance(p, str)]
            if paths:
                out[key] = paths
        return out

    def save_stats(self) -> None:
        self._stats_path.write_text(json.dumps(self.song_stats, indent=2), encoding="utf-8")

    def save_saved_playlists(self) -> None:
        ordered = {name: self.saved_playlists[name] for name in sorted(self.saved_playlists)}
        self._saved_playlists_path.write_text(json.dumps(ordered, indent=2), encoding="utf-8")

    @staticmethod
    def _normalize_playlist_name(name: str) -> str:
        return " ".join(name.strip().split())

    def list_saved_playlists(self) -> List[str]:
        return sorted(self.saved_playlists.keys(), key=str.lower)

    def save_current_playlist(self, name: str) -> bool:
        normalized = self._normalize_playlist_name(name)
        if not normalized or not self.playlist:
            return False

        self.saved_playlists[normalized] = [str(p) for p in self.playlist]
        self.save_saved_playlists()
        return True

    def delete_saved_playlist(self, name: str) -> bool:
        normalized = self._normalize_playlist_name(name)
        if normalized not in self.saved_playlists:
            return False
        del self.saved_playlists[normalized]
        self.save_saved_playlists()
        return True

    def load_saved_playlist(
        self,
        name: str,
        shuffle: bool = False,
        seed: str | int | None = None,
    ) -> str | None:
        normalized = self._normalize_playlist_name(name)
        entries = self.saved_playlists.get(normalized, [])
        paths = [Path(p) for p in entries]
        return self.set_playlist(paths, shuffle=shuffle, seed=seed)

    def update_stat(self, song_name: str, key: str) -> None:
        entry = self.song_stats.setdefault(song_name, {"played": 0, "started": 0, "skipped": 0})
        if key in entry:
            entry[key] += 1
            self.save_stats()

    def load_folder(
        self,
        folder_path: Path,
        shuffle: bool = True,
        seed: str | int | None = None,
        recursive: bool = False,
    ) -> str | None:
        if not folder_path.exists() or not folder_path.is_dir():
            return None
        scanner = folder_path.rglob("*") if recursive else folder_path.iterdir()
        songs = [
            p
            for p in scanner
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
