from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess
from pathlib import Path
from typing import Callable, List, Optional


def download_youtube_playlist(
    url: str,
    output_dir: Path,
    progress_hook: Optional[Callable[[str], None]] = None,
) -> List[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    def emit(message: str) -> None:
        if progress_hook:
            progress_hook(message)

    emit("Starting download...")

    try:
        return _download_with_library(url, output_dir, emit)
    except Exception as err:
        emit(f"yt-dlp library path failed ({err}); trying CLI fallback...")
        return _download_with_cli(url, output_dir, emit)


@dataclass
class YouTubeSearchResult:
    title: str
    channel: str
    duration_seconds: int
    webpage_url: str
    query_hint: str

    def duration_text(self) -> str:
        total = max(0, int(self.duration_seconds))
        return f"{total // 60}:{total % 60:02d}"


def search_youtube_songs(query: str, limit: int = 10) -> List[YouTubeSearchResult]:
    clean = query.strip()
    if not clean:
        return []

    try:
        import yt_dlp
    except Exception as err:
        raise RuntimeError("yt-dlp Python package is required for search.") from err

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    out: List[YouTubeSearchResult] = []
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{max(1, int(limit))}:{clean}", download=False)
        entries = info.get("entries", []) if isinstance(info, dict) else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title", "")).strip()
            if not title:
                continue

            channel = str(
                entry.get("channel")
                or entry.get("uploader")
                or entry.get("channel_id")
                or "Unknown Channel"
            ).strip()
            webpage_url = str(entry.get("webpage_url") or entry.get("url") or "").strip()
            if webpage_url and not webpage_url.startswith("http"):
                webpage_url = f"https://www.youtube.com/watch?v={webpage_url}"

            duration_seconds = 0
            try:
                duration_seconds = int(entry.get("duration", 0) or 0)
            except (TypeError, ValueError):
                duration_seconds = 0

            out.append(
                YouTubeSearchResult(
                    title=title,
                    channel=channel or "Unknown Channel",
                    duration_seconds=max(0, duration_seconds),
                    webpage_url=webpage_url,
                    query_hint=f"{title} {channel} audio",
                )
            )
    return out


def download_youtube_queries(
    queries: List[str],
    output_dir: Path,
    progress_hook: Optional[Callable[[str], None]] = None,
) -> List[Path]:
    cleaned = [" ".join(q.strip().split()) for q in queries if q and q.strip()]
    if not cleaned:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)

    def emit(message: str) -> None:
        if progress_hook:
            progress_hook(message)

    emit(f"Preparing {len(cleaned)} searches...")
    try:
        return _download_queries_with_library(cleaned, output_dir, emit)
    except Exception as err:
        emit(f"yt-dlp library query path failed ({err}); trying CLI fallback...")
        return _download_queries_with_cli(cleaned, output_dir, emit)


def _download_with_library(url: str, output_dir: Path, emit: Callable[[str], None]) -> List[Path]:
    import yt_dlp

    outtmpl = str(output_dir / "%(playlist_index)s - %(title)s.%(ext)s")
    downloaded_files: List[Path] = []

    def hook(data: dict) -> None:
        status = data.get("status")
        if status == "downloading":
            filename = Path(data.get("filename", "")).name
            pct = data.get("_percent_str", "").strip()
            emit(f"Downloading {filename} {pct}")
        elif status == "finished":
            filename = Path(data.get("filename", "")).name
            emit(f"Finished downloading {filename}, converting to MP3...")

    opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": False,
        "ignoreerrors": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "progress_hooks": [hook],
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        entries = info.get("entries", []) if isinstance(info, dict) else []
        for entry in entries:
            if not entry:
                continue
            title = entry.get("title")
            playlist_index = entry.get("playlist_index")
            if title is None or playlist_index is None:
                continue
            pattern = f"{playlist_index} - {title}".replace("/", "_")
            for song in output_dir.glob("*.mp3"):
                if song.stem.startswith(pattern):
                    downloaded_files.append(song)

    files = sorted(set(downloaded_files), key=lambda p: p.name.lower())
    if not files:
        files = sorted(output_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
    emit(f"Downloaded {len(files)} tracks.")
    return files


def _download_queries_with_library(
    queries: List[str], output_dir: Path, emit: Callable[[str], None]
) -> List[Path]:
    import yt_dlp

    outtmpl = str(output_dir / "%(autonumber)03d - %(title)s.%(ext)s")
    opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "ignoreerrors": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "quiet": True,
        "no_warnings": True,
        "autonumber_start": 1,
    }

    before = {p.resolve() for p in output_dir.glob("*.mp3")}
    with yt_dlp.YoutubeDL(opts) as ydl:
        for idx, query in enumerate(queries, start=1):
            emit(f"[{idx}/{len(queries)}] Downloading: {query}")
            ydl.extract_info(f"ytsearch1:{query}", download=True)

    files = sorted({p.resolve() for p in output_dir.glob("*.mp3")} - before, key=lambda p: p.name.lower())
    if not files:
        files = sorted(output_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
    emit(f"Downloaded {len(files)} tracks from search.")
    return [Path(p) for p in files]


def _download_with_cli(url: str, output_dir: Path, emit: Callable[[str], None]) -> List[Path]:
    yt_dlp_bin = shutil.which("yt-dlp")
    if not yt_dlp_bin:
        raise RuntimeError("yt-dlp is not installed (Python package and CLI not found).")

    cmd = [
        yt_dlp_bin,
        "-x",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "192K",
        "--yes-playlist",
        "-o",
        str(output_dir / "%(playlist_index)s - %(title)s.%(ext)s"),
        url,
    ]
    subprocess.run(cmd, check=True)

    files = sorted(output_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
    emit(f"Downloaded {len(files)} tracks.")
    return files


def _download_queries_with_cli(
    queries: List[str], output_dir: Path, emit: Callable[[str], None]
) -> List[Path]:
    yt_dlp_bin = shutil.which("yt-dlp")
    if not yt_dlp_bin:
        raise RuntimeError("yt-dlp is not installed (Python package and CLI not found).")

    before = {p.resolve() for p in output_dir.glob("*.mp3")}
    for idx, query in enumerate(queries, start=1):
        emit(f"[{idx}/{len(queries)}] Downloading: {query}")
        cmd = [
            yt_dlp_bin,
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "192K",
            "--no-playlist",
            "-o",
            str(output_dir / f"{idx:03d} - %(title)s.%(ext)s"),
            f"ytsearch1:{query}",
        ]
        subprocess.run(cmd, check=True)

    files = sorted({p.resolve() for p in output_dir.glob("*.mp3")} - before, key=lambda p: p.name.lower())
    if not files:
        files = sorted(output_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
    emit(f"Downloaded {len(files)} tracks from search.")
    return [Path(p) for p in files]
