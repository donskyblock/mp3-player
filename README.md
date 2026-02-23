# Pulse Player

A desktop MP3 player with a Spotify-like UI built on PySide6, with PyAudio playback and YouTube playlist downloading.

## Features

- Modern non-Tkinter desktop UI
- Folder-based audio library loading
- Search and double-click play
- Deterministic seeded shuffle (reuse a seed to reproduce order)
- Prev / Play-Pause / Next controls
- Seek bar and live time updates
- Volume slider and keyboard shortcuts
- Track stats: started / played / skipped
- Auto volume adjust mode ("Schizo mode")
- Light and dark themes
- YouTube playlist downloader via `yt-dlp`

## Requirements

- Python 3.10+
- `ffmpeg` installed and available in `PATH` (required for YouTube audio extraction and some audio decoding)

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

- `Space`: Play/Pause
- `Ctrl+Right`: Next track
- `Ctrl+Left`: Previous track
- `Ctrl+Up`: Volume up
- `Ctrl+Down`: Volume down

## Seeded Shuffle

- Use the `Shuffle seed` field to control playlist shuffle order.
- Enter any seed string and click `Shuffle` to get a repeatable order.
- Leave it blank to generate a random seed automatically.
- The active seed is shown in the field/status bar so you can save and reuse it later.

## Notes

- App stats are stored in:
  - Windows: `%APPDATA%/PythonMP3Player/stats.json`
  - macOS: `~/Library/Application Support/PythonMP3Player/stats.json`
  - Linux: `~/.local/share/PythonMP3Player/stats.json`
- YouTube downloads rely on `yt-dlp` and `ffmpeg`.
- Native executables are platform-specific. Build on each target OS for best results.
