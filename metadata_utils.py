from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AudioMetadata:
    title: str
    artist: str
    album: str
    year: str
    genre: str
    duration_seconds: float
    bitrate_kbps: int

    def display_title(self) -> str:
        if self.artist and self.artist != "Unknown Artist":
            return f"{self.artist} - {self.title}"
        return self.title


_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_LEADING_INDEX = re.compile(r"^\s*\d{1,3}\s*[-_.\)]\s*")


def _norm_key(value: str) -> str:
    return _NON_ALNUM.sub("", value.lower())


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\x00", " ").split()).strip()


def _parse_filename_title_artist(path: Path) -> tuple[str, str]:
    stem = _LEADING_INDEX.sub("", path.stem)
    stem = stem.replace("_", " ").strip()
    separators = [" - ", " — ", " – "]
    for sep in separators:
        if sep in stem:
            left, right = stem.split(sep, 1)
            artist = _clean_text(left)
            title = _clean_text(right)
            if artist and title:
                return artist, title
    return "", _clean_text(stem) or path.stem


def _parse_year(value: str) -> str:
    clean = _clean_text(value)
    if not clean:
        return ""
    # Also supports dates like YYYY-MM-DD and timestamps with year prefix.
    if len(clean) >= 4 and clean[:4].isdigit():
        return clean[:4]
    for i in range(len(value) - 3):
        chunk = value[i : i + 4]
        if chunk.isdigit():
            return chunk
    return ""


def _to_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_kbps(value: object) -> int:
    try:
        bits = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, bits // 1000)


def _first_tag(tags: dict[str, str], aliases: list[str]) -> str:
    normalized = {_norm_key(k): v for k, v in tags.items()}
    for alias in aliases:
        value = normalized.get(_norm_key(alias), "")
        if isinstance(value, str):
            clean = _clean_text(value)
            if clean:
                return clean
    return ""


def _read_ytdlp_info_metadata(path: Path) -> dict[str, object]:
    candidates: list[Path] = []
    candidates.append(Path(str(path) + ".info.json"))
    candidates.append(path.with_suffix(".info.json"))
    candidates.extend(path.parent.glob(f"{path.stem}*.info.json"))

    checked: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in checked:
            continue
        checked.add(key)
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return {}


def _merge_ytdlp_metadata(base: AudioMetadata, ytdlp_data: dict[str, object]) -> AudioMetadata:
    if not ytdlp_data:
        return base

    title = _clean_text(
        str(
            ytdlp_data.get("track")
            or ytdlp_data.get("title")
            or ""
        )
    ) or base.title

    artist_candidates = [
        ytdlp_data.get("artist"),
        ytdlp_data.get("album_artist"),
        ytdlp_data.get("uploader"),
        ytdlp_data.get("channel"),
        ytdlp_data.get("creator"),
    ]
    ytdlp_artist = ""
    for candidate in artist_candidates:
        clean = _clean_text(str(candidate or ""))
        if clean:
            ytdlp_artist = clean
            break
    artist = base.artist
    if (not artist or artist == "Unknown Artist") and ytdlp_artist:
        artist = ytdlp_artist

    album = _clean_text(str(ytdlp_data.get("album") or ytdlp_data.get("playlist_title") or "")) or base.album
    year = base.year or _parse_year(
        str(ytdlp_data.get("release_date") or ytdlp_data.get("upload_date") or ytdlp_data.get("timestamp") or "")
    )

    genre = base.genre
    categories = ytdlp_data.get("categories")
    if not genre and isinstance(categories, list):
        for entry in categories:
            clean = _clean_text(str(entry))
            if clean:
                genre = clean
                break
    if not genre:
        genre = _clean_text(str(ytdlp_data.get("genre") or ""))

    duration_seconds = base.duration_seconds
    if duration_seconds <= 0:
        duration_seconds = _to_float(ytdlp_data.get("duration"))

    return AudioMetadata(
        title=title or base.title,
        artist=artist or base.artist,
        album=album or base.album,
        year=year,
        genre=genre,
        duration_seconds=max(0.0, duration_seconds),
        bitrate_kbps=base.bitrate_kbps,
    )


def read_audio_metadata(path: Path) -> AudioMetadata:
    filename_artist, filename_title = _parse_filename_title_artist(path)
    fallback = AudioMetadata(
        title=filename_title or path.stem,
        artist=filename_artist or "Unknown Artist",
        album="Unknown Album",
        year="",
        genre="",
        duration_seconds=0.0,
        bitrate_kbps=0,
    )
    ytdlp_data = _read_ytdlp_info_metadata(path)

    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin:
        return _merge_ytdlp_metadata(fallback, ytdlp_data)

    cmd = [
        ffprobe_bin,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=7, check=False)
    except Exception:
        return _merge_ytdlp_metadata(fallback, ytdlp_data)

    if proc.returncode != 0 or not proc.stdout.strip():
        return _merge_ytdlp_metadata(fallback, ytdlp_data)

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return _merge_ytdlp_metadata(fallback, ytdlp_data)

    format_data = data.get("format", {}) if isinstance(data, dict) else {}
    streams = data.get("streams", []) if isinstance(data, dict) else []

    tags: dict[str, str] = {}
    if isinstance(format_data, dict):
        source_tags = format_data.get("tags", {})
        if isinstance(source_tags, dict):
            tags.update({str(k): str(v) for k, v in source_tags.items()})

    audio_stream = {}
    if isinstance(streams, list):
        for stream in streams:
            if isinstance(stream, dict) and stream.get("codec_type") == "audio":
                audio_stream = stream
                stream_tags = stream.get("tags", {})
                if isinstance(stream_tags, dict):
                    tags.update({str(k): str(v) for k, v in stream_tags.items()})
                break

    title = _first_tag(tags, ["title", "track", "song", "nam", "©nam"]) or fallback.title
    artist = _first_tag(
        tags,
        [
            "artist",
            "album_artist",
            "albumartist",
            "aART",
            "©ART",
            "performer",
            "composer",
        ],
    ) or fallback.artist
    album = _first_tag(tags, ["album", "©alb"]) or fallback.album
    year = _parse_year(
        _first_tag(tags, ["date", "year", "creation_time", "originaldate", "release_date"])
    )
    genre = _first_tag(tags, ["genre"])

    duration_seconds = _to_float(format_data.get("duration")) if isinstance(format_data, dict) else 0.0
    if duration_seconds <= 0 and isinstance(audio_stream, dict):
        duration_seconds = _to_float(audio_stream.get("duration"))

    bitrate_kbps = 0
    if isinstance(audio_stream, dict):
        bitrate_kbps = _to_kbps(audio_stream.get("bit_rate"))
    if bitrate_kbps <= 0 and isinstance(format_data, dict):
        bitrate_kbps = _to_kbps(format_data.get("bit_rate"))
    if bitrate_kbps <= 0:
        bitrate_kbps = _to_kbps(_first_tag(tags, ["bpm", "bps", "bitrate"]))

    # If tags missed artist and title was embedded in title field ("Artist - Title"), split.
    if (artist == "Unknown Artist" or not artist) and " - " in title:
        left, right = title.split(" - ", 1)
        possible_artist = _clean_text(left)
        possible_title = _clean_text(right)
        if possible_artist and possible_title:
            artist = possible_artist
            title = possible_title

    resolved = AudioMetadata(
        title=_clean_text(title) or fallback.title,
        artist=_clean_text(artist) or fallback.artist,
        album=_clean_text(album) or fallback.album,
        year=year,
        genre=_clean_text(genre),
        duration_seconds=max(0.0, duration_seconds),
        bitrate_kbps=bitrate_kbps,
    )
    return _merge_ytdlp_metadata(resolved, ytdlp_data)


def read_album_art_bytes(path: Path) -> bytes | None:
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        return None

    # First try attached-picture streams (common for MP3/M4A).
    primary_cmd = [
        ffmpeg_bin,
        "-v",
        "error",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-",
    ]
    try:
        proc = subprocess.run(primary_cmd, capture_output=True, timeout=8, check=False)
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout
    except Exception:
        pass

    # Fallback for files where ffmpeg exposes cover art differently.
    fallback_cmd = [
        ffmpeg_bin,
        "-v",
        "error",
        "-i",
        str(path),
        "-an",
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-",
    ]
    try:
        proc = subprocess.run(fallback_cmd, capture_output=True, timeout=8, check=False)
    except Exception:
        return None
    if proc.returncode == 0 and proc.stdout:
        return proc.stdout
    return None
