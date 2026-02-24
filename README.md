# Sabrinth Player

A pitch-black desktop audio player built with PySide6, with PyAudio playback, metadata awareness, ZIP import, saved playlists, and YouTube playlist downloading.

## Features

- Pitch-black hybrid style inspired by Spotify + YouTube Music
- Rebranded Sabrinth UI with custom sword SVG logo and animated glow
- Spotify-style queue table with per-track metadata columns
- Hero playlist banner and darker Spotify-inspired layout
- Embedded album-art thumbnails in queue rows, hero banner, now-playing panel, and saved playlist cards
- Startup and import loading screens with logo, spinner, and live progress text
- Background threaded imports (folder/ZIP/saved playlists) and async metadata/art hydration to keep UI responsive
- Customizable keybinds in Settings, including optional global system-wide hotkeys
- Deterministic seeded shuffle (reuse a seed to reproduce playlist order)
- Folder loading with optional recursive scanning
- ZIP archive import for music packs
- Spotify playlist import (via Spotify Web API + YouTube audio matching)
- Song finder modal (`Ctrl+K`) with search + multi-select download to build new queues
- Song search and downloads are YouTube-first (Spotify credentials not required for song search)
- Queue table sizing is locked to avoid window resizing jumps when song data changes
- Save, select, load, and delete named playlists
- Home page saved-playlists shelf with cards, plus a full library modal with all profiles
- Track metadata panel (artist, album, year, genre, duration, bitrate)
- Metadata fallback from yt-dlp `.info.json` sidecars when audio tags are missing
- Configurable settings menu with persistent preferences
- Debug menu with runtime snapshot panel and metadata cache refresh
- Downloaded YouTube playlists routed to a configured directory
- Search and double-click play
- Prev / Play/Pause / Next controls
- Seek bar and live time updates
- Volume slider, dynamic auto-adjust mode, and keyboard shortcuts
- Track stats: started / played / skipped

## Requirements

- Python 3.10+
- `ffmpeg` installed and available in `PATH` (required for YouTube audio extraction and some audio decoding)
- Spotify API app credentials for Spotify playlist import (`Client ID` + `Client Secret`)
- `pynput` for optional global (system-wide) hotkeys

## Install

```bash
pip install -r requirements.txt
```

## Quick Scripts

- Linux setup: `./scripts/setup_linux.sh`
- Linux/macOS run: `./scripts/run.sh`
- Windows run: `run_windows.bat`
- Build executable (Linux): `./scripts/build_linux.sh`
- Build executable (macOS): `./scripts/build_macos.sh`
- Build executable (Windows): `build_windows.bat`
- Build wrapper for current Unix platform: `./scripts/build_all.sh`

## Run

```bash
python main.py
```

## Keyboard Shortcuts

- Defaults:
- `Space`: Play/Pause
- `Ctrl+Right`: Next track
- `Ctrl+Left`: Previous track
- `Ctrl+Up`: Volume up
- `Ctrl+Down`: Volume down
- `Ctrl+K`: Find songs and add to queue
- `Ctrl+,`: Open settings
- `Ctrl+Shift+D`: Open debug panel
- `Ctrl+Q`: Quit app
- These can be changed in `Settings` and optionally enabled as global (system-wide) hotkeys.

## Seeded Shuffle

- Open `Library`, choose `Shuffle Playlist`, and provide a seed.
- Reusing the same seed reproduces the same order.
- Leave seed blank to generate a random one automatically.
- The active seed is shown in the status bar and reused for later shuffle actions.

## Saved Playlists

- Use `Library -> Save Current Playlist` to store the active queue under a name.
- Use `Library -> Load Saved Playlist` to restore a saved queue.
- Use `Library -> Delete Saved Playlist` to remove an entry.

## Settings

- Open settings from `Sabrinth -> Settings`, the `Settings` button, or `Ctrl+,`.
- Configuration includes theme, default volume, shuffle/autoplay behavior, recursive scan, dynamic volume default, download directory strategy, and Spotify API credentials.
- All settings persist to disk and are applied on startup.

## Spotify Import

- Add your Spotify app credentials in Settings:
- `Spotify client ID`
- `Spotify client secret`
- Use `Import -> Spotify Playlist` (or `Sabrinth -> Import Spotify Playlist`) and paste a public playlist URL.
- Tracks are resolved from Spotify metadata and downloaded as audio via YouTube search.

## Song Finder

- Use `Find Songs` (or `Ctrl+K`) to search for tracks.
- Select one or multiple results and choose whether to replace or append to your queue.
- Optionally save the downloaded result set as a named playlist in the same flow.

## Notes

- App data is stored in:
  - Windows: `%APPDATA%/SabrinthPlayer/`
  - macOS: `~/Library/Application Support/SabrinthPlayer/`
  - Linux: `~/.local/share/SabrinthPlayer/`
- `settings.json`, `stats.json`, ZIP imports, and default downloads live inside that app directory.
- YouTube downloads rely on `yt-dlp`, and metadata extraction uses `ffprobe` (typically shipped with `ffmpeg`).
- Global hotkeys depend on OS support (`pynput` backend); some Wayland setups may restrict system-wide key capture.
- Native executables are platform-specific. Build on each target OS for best results.
