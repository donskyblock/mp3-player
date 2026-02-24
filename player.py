from __future__ import annotations

import ctypes
import ctypes.util
import os
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Optional

import pyaudio


_ALSA_HANDLER_FUNC = ctypes.CFUNCTYPE(
    None,
    ctypes.c_char_p,
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_int,
    ctypes.c_char_p,
)
_ALSA_ERROR_HANDLER = None
_ASOUND_LIB = None


@contextmanager
def _suppress_stderr() -> None:
    try:
        stderr_fd = sys.stderr.fileno()
    except Exception:
        yield
        return

    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    saved_fd = os.dup(stderr_fd)
    try:
        os.dup2(devnull_fd, stderr_fd)
        yield
    finally:
        os.dup2(saved_fd, stderr_fd)
        os.close(saved_fd)
        os.close(devnull_fd)


def _mute_alsa_warnings() -> None:
    """Suppress libasound stderr noise when probing optional/nonexistent PCMs."""
    global _ALSA_ERROR_HANDLER, _ASOUND_LIB
    if _ALSA_ERROR_HANDLER is not None:
        return

    lib_path = ctypes.util.find_library("asound")
    if not lib_path:
        return
    try:
        _ASOUND_LIB = ctypes.cdll.LoadLibrary(lib_path)
    except OSError:
        return

    def _ignore_errors(_filename, _line, _function, _err, _fmt) -> None:
        return

    _ALSA_ERROR_HANDLER = _ALSA_HANDLER_FUNC(_ignore_errors)
    try:
        _ASOUND_LIB.snd_lib_error_set_handler(_ALSA_ERROR_HANDLER)
    except Exception:
        _ALSA_ERROR_HANDLER = None
        _ASOUND_LIB = None


def _scale_pcm(chunk: bytes, sample_width: int, volume: float) -> bytes:
    if volume >= 0.999:
        return chunk
    if volume <= 0.001:
        return b"\x00" * len(chunk)
    if sample_width not in (1, 2, 3, 4):
        return chunk

    out = bytearray(len(chunk))
    step = sample_width

    if sample_width == 1:
        # 8-bit PCM is unsigned.
        for i in range(0, len(chunk), step):
            s = chunk[i] - 128
            scaled = int(s * volume)
            if scaled > 127:
                scaled = 127
            elif scaled < -128:
                scaled = -128
            out[i] = scaled + 128
        return bytes(out)

    min_v = -(1 << (8 * sample_width - 1))
    max_v = (1 << (8 * sample_width - 1)) - 1
    for i in range(0, len(chunk), step):
        s = int.from_bytes(chunk[i : i + step], byteorder="little", signed=True)
        scaled = int(s * volume)
        if scaled > max_v:
            scaled = max_v
        elif scaled < min_v:
            scaled = min_v
        out[i : i + step] = scaled.to_bytes(step, byteorder="little", signed=True)
    return bytes(out)


class AudioPlayer:
    """Threaded audio player that decodes with ffmpeg and outputs via PyAudio."""

    def __init__(self, on_track_end: Optional[Callable[[], None]] = None) -> None:
        _mute_alsa_warnings()
        with _suppress_stderr():
            self._pa = pyaudio.PyAudio()
        self._stream = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._output_device_index = self._resolve_output_device_index()

        self._track_path: Optional[Path] = None
        self._raw_audio: bytes = b""
        self._frame_rate = 44100
        self._channels = 2
        self._sample_width = 2
        self._frame_count = 0
        self._position_frame = 0

        self._volume = 0.5
        self._playing = False
        self._paused = False

        self.on_track_end = on_track_end

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def duration_seconds(self) -> float:
        if not self._frame_rate:
            return 0.0
        return self._frame_count / self._frame_rate

    def current_seconds(self) -> float:
        with self._lock:
            if not self._frame_rate:
                return 0.0
            return self._position_frame / self._frame_rate

    def set_volume(self, value: float) -> None:
        self._volume = max(0.0, min(1.0, float(value)))

    def load_and_play(self, path: Path, start_seconds: float = 0.0) -> None:
        self.stop()
        self._track_path = path
        self._raw_audio = self._decode_audio(path)

        self._frame_rate = 44100
        self._channels = 2
        self._sample_width = 2

        frame_size = self._sample_width * self._channels
        self._frame_count = len(self._raw_audio) // frame_size

        clamped_start = max(0.0, min(start_seconds, self.duration_seconds))
        self._position_frame = int(clamped_start * self._frame_rate)

        self._stop_event.clear()
        self._paused = False
        self._playing = True
        self._thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=1.0)
        self._thread = None
        self._close_stream()
        self._playing = False
        self._paused = False

    def pause(self) -> None:
        if self._playing:
            self._paused = True

    def resume(self) -> None:
        if self._playing:
            self._paused = False

    def toggle_pause(self) -> None:
        if self._paused:
            self.resume()
        else:
            self.pause()

    def seek(self, seconds: float) -> None:
        with self._lock:
            clamped = max(0.0, min(seconds, self.duration_seconds))
            self._position_frame = int(clamped * self._frame_rate)

    def shutdown(self) -> None:
        self.stop()
        self._pa.terminate()

    def _resolve_output_device_index(self) -> Optional[int]:
        try:
            info = self._pa.get_default_output_device_info()
            index = info.get("index")
            if isinstance(index, int):
                return index
        except Exception:
            pass

        try:
            count = self._pa.get_device_count()
        except Exception:
            return None

        for idx in range(count):
            try:
                info = self._pa.get_device_info_by_index(idx)
            except Exception:
                continue
            channels = info.get("maxOutputChannels", 0)
            if isinstance(channels, (int, float)) and channels > 0:
                return idx
        return None

    def _decode_audio(self, path: Path) -> bytes:
        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            raise RuntimeError("ffmpeg is not installed or not in PATH.")

        cmd = [
            ffmpeg_bin,
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-",
        ]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ffmpeg decode failed for '{path.name}': {detail}")
        return proc.stdout

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop_stream()
            except Exception:
                pass
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _playback_loop(self) -> None:
        if not self._raw_audio:
            return

        format_ = self._pa.get_format_from_width(self._sample_width)
        try:
            open_kwargs = {
                "format": format_,
                "channels": self._channels,
                "rate": self._frame_rate,
                "output": True,
            }
            if self._output_device_index is not None:
                open_kwargs["output_device_index"] = self._output_device_index
            self._stream = self._pa.open(**open_kwargs)
        except Exception:
            self._playing = False
            self._paused = False
            return

        frame_size = self._sample_width * self._channels
        chunk_frames = 2048
        reached_end = False

        while not self._stop_event.is_set():
            if self._paused:
                time.sleep(0.05)
                continue

            with self._lock:
                start_frame = self._position_frame

            if start_frame >= self._frame_count:
                reached_end = True
                break

            end_frame = min(start_frame + chunk_frames, self._frame_count)
            start_byte = start_frame * frame_size
            end_byte = end_frame * frame_size
            chunk = self._raw_audio[start_byte:end_byte]
            if not chunk:
                reached_end = True
                break

            if self._volume < 0.999:
                chunk = _scale_pcm(chunk, self._sample_width, self._volume)

            try:
                self._stream.write(chunk)
            except Exception:
                break

            with self._lock:
                self._position_frame = end_frame

        self._close_stream()
        should_fire_callback = reached_end and not self._stop_event.is_set()
        self._playing = False
        self._paused = False

        if should_fire_callback and self.on_track_end is not None:
            self.on_track_end()
