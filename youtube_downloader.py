from __future__ import annotations

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
