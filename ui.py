from __future__ import annotations

import random
import time
from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from player import AudioPlayer
from playlist_manager import PlaylistManager
from youtube_downloader import download_youtube_playlist


class DownloadThread(QThread):
    status = Signal(str)
    finished_files = Signal(list)
    failed = Signal(str)

    def __init__(self, url: str, output_dir: Path) -> None:
        super().__init__()
        self.url = url
        self.output_dir = output_dir

    def run(self) -> None:
        try:
            files = download_youtube_playlist(self.url, self.output_dir, self.status.emit)
            self.finished_files.emit([str(p) for p in files])
        except Exception as err:
            self.failed.emit(str(err))


class MainWindow(QMainWindow):
    track_finished_signal = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pulse Player")
        self.resize(1120, 700)

        self.playlist_manager = PlaylistManager()
        self.player = AudioPlayer(on_track_end=self.track_finished_signal.emit)

        self.track_duration = 0.0
        self.slider_dragging = False
        self.auto_adjust_enabled = False
        self.next_adjust_at = 0.0
        self.dark_mode = True
        self.download_thread: DownloadThread | None = None

        self._build_ui()
        self._setup_shortcuts()
        self._connect_events()

        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(250)
        self.progress_timer.timeout.connect(self._update_progress)
        self.progress_timer.start()

        self.track_finished_signal.connect(self._on_track_finished)
        self._apply_theme()
        self._refresh_playlist_view()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 16, 20, 16)

        title = QLabel("Pulse Player")
        title.setObjectName("title")

        self.theme_btn = QPushButton("Light")
        self.theme_btn.setObjectName("ghostBtn")
        self.theme_btn.clicked.connect(self._toggle_theme)

        header_layout.addWidget(title)
        header_layout.addStretch(1)
        header_layout.addWidget(self.theme_btn)
        outer.addWidget(header)

        body = QFrame()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(20, 20, 20, 20)
        body_layout.setSpacing(20)

        left_panel = QFrame()
        left_panel.setObjectName("panel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(12)

        self.load_btn = QPushButton("Load Folder")
        self.load_btn.setObjectName("primaryBtn")
        left_layout.addWidget(self.load_btn)

        self.youtube_url = QLineEdit()
        self.youtube_url.setPlaceholderText("Paste YouTube playlist URL")
        left_layout.addWidget(self.youtube_url)

        self.download_btn = QPushButton("Download Playlist")
        self.download_btn.setObjectName("primaryBtn")
        left_layout.addWidget(self.download_btn)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search songs...")
        left_layout.addWidget(self.search_input)

        self.playlist_list = QListWidget()
        self.playlist_list.setObjectName("playlist")
        left_layout.addWidget(self.playlist_list, stretch=1)

        body_layout.addWidget(left_panel, stretch=3)

        right_panel = QFrame()
        right_panel.setObjectName("panel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(24, 24, 24, 24)
        right_layout.setSpacing(16)

        self.now_playing = QLabel("No track loaded")
        self.now_playing.setObjectName("nowPlaying")

        self.meta_label = QLabel("Load a folder or YouTube playlist to start")
        self.meta_label.setObjectName("meta")

        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 1000)

        timing_row = QHBoxLayout()
        self.time_current = QLabel("0:00")
        self.time_total = QLabel("0:00")
        self.time_current.setObjectName("time")
        self.time_total.setObjectName("time")
        timing_row.addWidget(self.time_current)
        timing_row.addStretch(1)
        timing_row.addWidget(self.time_total)

        controls = QHBoxLayout()
        self.prev_btn = QPushButton("Prev")
        self.play_btn = QPushButton("Play")
        self.next_btn = QPushButton("Next")
        for btn in (self.prev_btn, self.play_btn, self.next_btn):
            btn.setObjectName("controlBtn")
            controls.addWidget(btn)

        volume_row = QHBoxLayout()
        volume_label = QLabel("Volume")
        volume_label.setObjectName("meta")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.auto_btn = QPushButton("Schizo Mode: Off")
        self.auto_btn.setObjectName("ghostBtn")
        volume_row.addWidget(volume_label)
        volume_row.addWidget(self.volume_slider, stretch=1)
        volume_row.addWidget(self.auto_btn)

        right_layout.addWidget(self.now_playing)
        right_layout.addWidget(self.meta_label)
        right_layout.addSpacing(8)
        right_layout.addWidget(self.progress_slider)
        right_layout.addLayout(timing_row)
        right_layout.addSpacing(8)
        right_layout.addLayout(controls)
        right_layout.addStretch(1)
        right_layout.addLayout(volume_row)

        body_layout.addWidget(right_panel, stretch=2)
        outer.addWidget(body, stretch=1)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("Space"), self, activated=self._toggle_play)
        QShortcut(QKeySequence("Ctrl+Right"), self, activated=self.play_next)
        QShortcut(QKeySequence("Ctrl+Left"), self, activated=self.play_prev)
        QShortcut(QKeySequence("Ctrl+Up"), self, activated=self._volume_up)
        QShortcut(QKeySequence("Ctrl+Down"), self, activated=self._volume_down)

    def _connect_events(self) -> None:
        self.load_btn.clicked.connect(self.load_folder)
        self.download_btn.clicked.connect(self.download_playlist)
        self.search_input.textChanged.connect(self._on_search)
        self.search_input.returnPressed.connect(self._play_first_search_result)
        self.playlist_list.itemDoubleClicked.connect(self._play_selected_item)

        self.play_btn.clicked.connect(self._toggle_play)
        self.next_btn.clicked.connect(self.play_next)
        self.prev_btn.clicked.connect(self.play_prev)
        self.volume_slider.valueChanged.connect(self._on_volume_change)
        self.auto_btn.clicked.connect(self._toggle_auto_adjust)

        self.progress_slider.sliderPressed.connect(self._on_slider_pressed)
        self.progress_slider.sliderReleased.connect(self._on_slider_released)

    def _refresh_playlist_view(self) -> None:
        self.playlist_list.clear()
        for song in self.playlist_manager.filtered_playlist:
            stats = self.playlist_manager.stats_for(song)
            text = f"{song.name}  |  started {stats.started}  played {stats.played}  skipped {stats.skipped}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, str(song))
            self.playlist_list.addItem(item)

    def load_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose audio folder")
        if not folder:
            return
        self.playlist_manager.load_folder(Path(folder), shuffle=True)
        self._refresh_playlist_view()
        self.status_bar.showMessage(f"Loaded {len(self.playlist_manager.playlist)} tracks")
        if self.playlist_manager.playlist:
            self.play_track(0)

    def _on_search(self, text: str) -> None:
        self.playlist_manager.apply_search(text)
        self._refresh_playlist_view()

    def _play_first_search_result(self) -> None:
        if not self.playlist_manager.filtered_playlist:
            return
        first = self.playlist_manager.filtered_playlist[0]
        try:
            idx = self.playlist_manager.playlist.index(first)
        except ValueError:
            return
        self.play_track(idx)

    def _play_selected_item(self, item: QListWidgetItem) -> None:
        path_str = item.data(Qt.ItemDataRole.UserRole)
        if not path_str:
            return
        song = Path(path_str)
        try:
            idx = self.playlist_manager.playlist.index(song)
        except ValueError:
            return
        self.play_track(idx)

    def _toggle_play(self) -> None:
        if not self.playlist_manager.playlist:
            return

        if self.player.playing and not self.player.paused:
            self.player.pause()
            self.play_btn.setText("Resume")
            self.status_bar.showMessage("Paused")
            return

        if self.player.paused:
            self.player.resume()
            self.play_btn.setText("Pause")
            self.status_bar.showMessage("Playing")
            return

        self.play_track(self.playlist_manager.index)

    def play_track(self, index: int, start_seconds: float = 0.0) -> None:
        if not self.playlist_manager.playlist:
            return

        idx = index % len(self.playlist_manager.playlist)
        self.playlist_manager.index = idx
        song = self.playlist_manager.playlist[idx]

        try:
            self.player.load_and_play(song, start_seconds=start_seconds)
        except Exception as err:
            QMessageBox.critical(self, "Playback Error", f"Could not play file:\n{song}\n\n{err}")
            return

        self.playlist_manager.update_stat(song.name, "started")
        self.track_duration = self.player.duration_seconds

        self.now_playing.setText(song.stem)
        self.meta_label.setText(str(song.parent))
        self.time_total.setText(self._fmt_seconds(self.track_duration))
        self.play_btn.setText("Pause")
        self.status_bar.showMessage(f"Now playing: {song.name}")

        self._refresh_playlist_view()
        for i in range(self.playlist_list.count()):
            item = self.playlist_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == str(song):
                self.playlist_list.setCurrentItem(item)
                break

    def play_next(self) -> None:
        if not self.playlist_manager.playlist:
            return
        current = self.playlist_manager.playlist[self.playlist_manager.index]
        self.playlist_manager.update_stat(current.name, "skipped")
        self.play_track(self.playlist_manager.next_index())

    def play_prev(self) -> None:
        if not self.playlist_manager.playlist:
            return
        current = self.playlist_manager.playlist[self.playlist_manager.index]
        self.playlist_manager.update_stat(current.name, "skipped")
        self.play_track(self.playlist_manager.prev_index())

    def _on_track_finished(self) -> None:
        if not self.playlist_manager.playlist:
            return
        song = self.playlist_manager.playlist[self.playlist_manager.index]
        self.playlist_manager.update_stat(song.name, "played")
        self.play_track(self.playlist_manager.next_index())

    def _on_volume_change(self, value: int) -> None:
        volume = value / 100.0
        self.player.set_volume(volume)
        self.status_bar.showMessage(f"Volume: {value}%")

    def _volume_up(self) -> None:
        self.volume_slider.setValue(min(100, self.volume_slider.value() + 1))

    def _volume_down(self) -> None:
        self.volume_slider.setValue(max(0, self.volume_slider.value() - 1))

    def _on_slider_pressed(self) -> None:
        self.slider_dragging = True

    def _on_slider_released(self) -> None:
        self.slider_dragging = False
        if self.track_duration <= 0:
            return
        fraction = self.progress_slider.value() / 1000.0
        target = fraction * self.track_duration
        self.player.seek(target)

    def _update_progress(self) -> None:
        if self.player.playing:
            current = self.player.current_seconds()
            self.time_current.setText(self._fmt_seconds(current))
            if not self.slider_dragging and self.track_duration > 0:
                fraction = max(0.0, min(1.0, current / self.track_duration))
                self.progress_slider.setValue(int(fraction * 1000))

        if self.auto_adjust_enabled and time.time() >= self.next_adjust_at:
            change = 0.0 if random.choice((True, False)) else -0.03
            current_volume = self.volume_slider.value() / 100.0
            new_volume = max(0.0, min(1.0, current_volume + change))
            self.volume_slider.setValue(int(new_volume * 100))
            self.status_bar.showMessage(f"Auto adjusted volume to {int(new_volume * 100)}%")
            self.next_adjust_at = time.time() + random.randint(5 * 60, 30 * 60)

    def _toggle_auto_adjust(self) -> None:
        self.auto_adjust_enabled = not self.auto_adjust_enabled
        if self.auto_adjust_enabled:
            self.next_adjust_at = time.time() + random.randint(5 * 60, 30 * 60)
            self.auto_btn.setText("Schizo Mode: On")
            self.status_bar.showMessage("Schizo mode enabled")
        else:
            self.auto_btn.setText("Schizo Mode: Off")
            self.status_bar.showMessage("Schizo mode disabled")

    def download_playlist(self) -> None:
        url = self.youtube_url.text().strip()
        if not url:
            QMessageBox.information(self, "Missing URL", "Paste a YouTube playlist URL first.")
            return

        folder = QFileDialog.getExistingDirectory(self, "Choose download folder")
        if not folder:
            return

        self.download_btn.setEnabled(False)
        self.status_bar.showMessage("Downloading playlist...")

        self.download_thread = DownloadThread(url, Path(folder))
        self.download_thread.status.connect(self.status_bar.showMessage)
        self.download_thread.failed.connect(self._download_failed)
        self.download_thread.finished_files.connect(self._download_done)
        self.download_thread.finished.connect(lambda: self.download_btn.setEnabled(True))
        self.download_thread.start()

    def _download_done(self, files: List[str]) -> None:
        songs = [Path(p) for p in files]
        self.playlist_manager.set_playlist(songs, shuffle=False)
        self._refresh_playlist_view()
        self.status_bar.showMessage(f"Playlist ready with {len(songs)} tracks")
        if songs:
            self.play_track(0)

    def _download_failed(self, message: str) -> None:
        QMessageBox.critical(
            self,
            "Download Failed",
            "Could not download playlist.\n"
            "Make sure yt-dlp and ffmpeg are installed and the URL is valid.\n\n"
            f"Details: {message}",
        )
        self.status_bar.showMessage("Download failed")

    @staticmethod
    def _fmt_seconds(seconds: float) -> str:
        s = max(0, int(seconds))
        return f"{s // 60}:{s % 60:02d}"

    def _toggle_theme(self) -> None:
        self.dark_mode = not self.dark_mode
        self._apply_theme()

    def _apply_theme(self) -> None:
        if self.dark_mode:
            self.theme_btn.setText("Light")
            self.setStyleSheet(
                """
                QMainWindow { background: #0d1117; }
                #header { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #121923, stop:1 #0f2530); border-bottom: 1px solid #273442; }
                #title { color: #e8f1f7; font-size: 28px; font-weight: 700; letter-spacing: 1px; }
                #panel { background: #111a24; border: 1px solid #243445; border-radius: 12px; }
                QLineEdit { background: #0e151d; color: #dce7ef; border: 1px solid #2a3b4d; border-radius: 8px; padding: 8px; }
                QListWidget#playlist { background: #0e151d; color: #d7e3ec; border: 1px solid #2a3b4d; border-radius: 8px; }
                QListWidget::item:selected { background: #1f8a70; color: #ffffff; }
                QPushButton { color: #dde8ef; border-radius: 8px; padding: 8px 14px; border: 1px solid #34506a; background: #152434; }
                QPushButton#primaryBtn { background: #1f8a70; border: 1px solid #1f8a70; color: white; font-weight: 600; }
                QPushButton#controlBtn { background: #1a2a3a; font-weight: 600; }
                QPushButton#ghostBtn { background: transparent; border: 1px solid #3a556f; }
                QLabel#nowPlaying { color: #f0f6fa; font-size: 26px; font-weight: 700; }
                QLabel#meta { color: #8ca2b5; font-size: 13px; }
                QLabel#time { color: #9cb3c6; }
                QSlider::groove:horizontal { background: #223648; height: 6px; border-radius: 3px; }
                QSlider::handle:horizontal { background: #1f8a70; width: 16px; margin: -5px 0; border-radius: 8px; }
                QStatusBar { background: #0f1620; color: #aac0d2; border-top: 1px solid #223241; }
                """
            )
        else:
            self.theme_btn.setText("Dark")
            self.setStyleSheet(
                """
                QMainWindow { background: #f4f7fa; }
                #header { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #c8d8e8, stop:1 #d8e9e1); border-bottom: 1px solid #c0d0df; }
                #title { color: #1f2f3d; font-size: 28px; font-weight: 700; letter-spacing: 1px; }
                #panel { background: #ffffff; border: 1px solid #d6e1eb; border-radius: 12px; }
                QLineEdit { background: #fbfdff; color: #1b2a38; border: 1px solid #c5d3e0; border-radius: 8px; padding: 8px; }
                QListWidget#playlist { background: #fcfeff; color: #223445; border: 1px solid #c5d3e0; border-radius: 8px; }
                QListWidget::item:selected { background: #36a37c; color: white; }
                QPushButton { color: #1f3040; border-radius: 8px; padding: 8px 14px; border: 1px solid #b2c3d3; background: #eaf0f5; }
                QPushButton#primaryBtn { background: #2d9b75; border: 1px solid #2d9b75; color: white; font-weight: 600; }
                QPushButton#controlBtn { background: #edf3f8; font-weight: 600; }
                QPushButton#ghostBtn { background: transparent; border: 1px solid #b2c3d3; }
                QLabel#nowPlaying { color: #1a2a38; font-size: 26px; font-weight: 700; }
                QLabel#meta { color: #5f7488; font-size: 13px; }
                QLabel#time { color: #567087; }
                QSlider::groove:horizontal { background: #c8d8e6; height: 6px; border-radius: 3px; }
                QSlider::handle:horizontal { background: #2d9b75; width: 16px; margin: -5px 0; border-radius: 8px; }
                QStatusBar { background: #e9f0f6; color: #385266; border-top: 1px solid #ccd9e5; }
                """
            )

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.player.shutdown()
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.quit()
            self.download_thread.wait(1000)
        super().closeEvent(event)
