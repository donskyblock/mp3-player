from __future__ import annotations

import audioop
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import pyaudio
from pydub import AudioSegment


class AudioPlayer:
    """Threaded audio player that decodes with pydub and outputs via PyAudio."""

    def __init__(self, on_track_end: Optional[Callable[[], None]] = None) -> None:
        self._pa = pyaudio.PyAudio()
        self._stream = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        self._segment: Optional[AudioSegment] = None
        self._track_path: Optional[Path] = None
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
        self._segment = AudioSegment.from_file(path)
        self._track_path = path

        self._frame_rate = self._segment.frame_rate
        self._channels = self._segment.channels
        self._sample_width = self._segment.sample_width

        frame_size = self._sample_width * self._channels
        self._frame_count = len(self._segment.raw_data) // frame_size

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
        if self._segment is None:
            return

        format_ = self._pa.get_format_from_width(self._sample_width)
        self._stream = self._pa.open(
            format=format_,
            channels=self._channels,
            rate=self._frame_rate,
            output=True,
        )

        frame_size = self._sample_width * self._channels
        chunk_frames = 2048
        raw = self._segment.raw_data
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
            chunk = raw[start_byte:end_byte]
            if not chunk:
                reached_end = True
                break

            if self._volume < 0.999:
                chunk = audioop.mul(chunk, self._sample_width, self._volume)

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
