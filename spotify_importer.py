from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Callable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


@dataclass
class SpotifyTrack:
    title: str
    artists: List[str]
    album: str
    duration_ms: int

    def search_query(self) -> str:
        artist = ", ".join(self.artists) if self.artists else ""
        if artist:
            return f"{artist} - {self.title} audio"
        return f"{self.title} audio"


def _emit(callback: Optional[Callable[[str], None]], message: str) -> None:
    if callback:
        callback(message)


def parse_spotify_playlist_id(raw: str) -> str:
    text = raw.strip()
    if not text:
        raise ValueError("Missing Spotify playlist URL.")

    if text.startswith("spotify:playlist:"):
        return text.split(":")[-1].strip()

    parsed = urlparse(text)
    if parsed.netloc not in {"open.spotify.com", "play.spotify.com"}:
        raise ValueError("Expected an open.spotify.com playlist URL.")

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "playlist":
        return parts[1]

    query = parse_qs(parsed.query)
    if "playlist" in query and query["playlist"]:
        return query["playlist"][0]

    raise ValueError("Could not parse playlist ID from URL.")


def _http_json(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None = None,
    timeout: float = 12.0,
) -> dict:
    req = Request(url=url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            content = response.read().decode("utf-8")
    except HTTPError as err:
        try:
            detail = err.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(err)
        raise RuntimeError(f"Spotify request failed ({err.code}): {detail}") from err
    except URLError as err:
        raise RuntimeError(f"Spotify request failed: {err}") from err

    try:
        data = json.loads(content)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"Spotify returned invalid JSON: {err}") from err
    if not isinstance(data, dict):
        raise RuntimeError("Spotify returned an invalid payload type.")
    return data


def _spotify_access_token(client_id: str, client_secret: str) -> str:
    if not client_id.strip() or not client_secret.strip():
        raise ValueError(
            "Spotify API credentials are missing. Set Client ID and Client Secret in Settings."
        )

    auth = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    body = b"grant_type=client_credentials"
    data = _http_json(
        "POST",
        "https://accounts.spotify.com/api/token",
        headers=headers,
        body=body,
        timeout=12.0,
    )
    token = str(data.get("access_token", "")).strip()
    if not token:
        raise RuntimeError("Spotify token response did not include an access token.")
    return token


def fetch_spotify_playlist_tracks(
    playlist_url: str,
    client_id: str,
    client_secret: str,
    progress_hook: Optional[Callable[[str], None]] = None,
) -> tuple[str, List[SpotifyTrack]]:
    playlist_id = parse_spotify_playlist_id(playlist_url)
    _emit(progress_hook, "Requesting Spotify access token...")
    token = _spotify_access_token(client_id, client_secret)

    headers = {"Authorization": f"Bearer {token}"}
    playlist_meta_url = f"https://api.spotify.com/v1/playlists/{playlist_id}?fields=name"
    meta = _http_json("GET", playlist_meta_url, headers=headers, timeout=12.0)
    playlist_name = str(meta.get("name", "")).strip() or "Spotify Playlist"
    _emit(progress_hook, f"Fetching tracks from '{playlist_name}'...")

    tracks: List[SpotifyTrack] = []
    next_url = (
        f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        "?limit=100"
        "&fields=items(is_local,track(name,artists(name),album(name),duration_ms)),next,total"
    )
    seen = 0

    while next_url:
        payload = _http_json("GET", next_url, headers=headers, timeout=15.0)
        items = payload.get("items", [])
        if not isinstance(items, list):
            break

        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("is_local"):
                continue
            track = item.get("track", {})
            if not isinstance(track, dict):
                continue

            title = str(track.get("name", "")).strip()
            if not title:
                continue
            artist_entries = track.get("artists", [])
            artists: List[str] = []
            if isinstance(artist_entries, list):
                for art in artist_entries:
                    if isinstance(art, dict):
                        name = str(art.get("name", "")).strip()
                        if name:
                            artists.append(name)
            album_name = ""
            album = track.get("album", {})
            if isinstance(album, dict):
                album_name = str(album.get("name", "")).strip()
            duration_ms = 0
            try:
                duration_ms = int(track.get("duration_ms", 0))
            except (TypeError, ValueError):
                duration_ms = 0

            tracks.append(
                SpotifyTrack(
                    title=title,
                    artists=artists,
                    album=album_name,
                    duration_ms=max(0, duration_ms),
                )
            )

        seen += len(items)
        total = payload.get("total")
        if isinstance(total, int) and total > 0:
            _emit(progress_hook, f"Fetched {min(seen, total)} / {total} Spotify tracks...")
        else:
            _emit(progress_hook, f"Fetched {seen} Spotify tracks...")

        raw_next = payload.get("next")
        next_url = str(raw_next).strip() if isinstance(raw_next, str) else ""

    if not tracks:
        raise RuntimeError(
            "No playable tracks were found in this Spotify playlist. "
            "If the playlist is private, make it public and try again."
        )

    _emit(progress_hook, f"Found {len(tracks)} Spotify tracks.")
    return playlist_name, tracks
