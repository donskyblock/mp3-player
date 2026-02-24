from __future__ import annotations

import math
import random
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List

from PySide6.QtCore import QSize, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QStatusBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from metadata_utils import AudioMetadata, read_album_art_bytes, read_audio_metadata
from player import AudioPlayer
from playlist_manager import PlaylistManager, SUPPORTED_EXTENSIONS
from spotify_importer import fetch_spotify_playlist_tracks
from settings_manager import SettingsManager
from youtube_downloader import (
    YouTubeSearchResult,
    download_youtube_playlist,
    download_youtube_queries,
    search_youtube_songs,
)


ASSET_DIR = Path(__file__).resolve().parent / "assets"
LOGO_PATH = ASSET_DIR / "sabrinth_logo.svg"
THEME_OPTIONS = {
    "Pitch Black": "pitch_black",
}


class LoadingDialog(QDialog):
    _SPINNER_FRAMES = ("◐", "◓", "◑", "◒")

    def __init__(
        self,
        message: str = "Loading...",
        parent: QWidget | None = None,
        modal: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("loadingDialog")
        self.setWindowTitle("Sabrinth Player")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setModal(modal)
        if modal:
            self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setFixedSize(420, 236)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 18)
        root.setSpacing(12)

        self.logo = QLabel()
        self.logo.setObjectName("loadingLogo")
        self.logo.setFixedSize(84, 84)
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if LOGO_PATH.exists():
            pix = QPixmap(str(LOGO_PATH))
            if not pix.isNull():
                self.logo.setPixmap(
                    pix.scaled(
                        74,
                        74,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        if self.logo.pixmap() is None:
            self.logo.setText("S")

        self.spinner = QLabel(self._SPINNER_FRAMES[0])
        self.spinner.setObjectName("loadingSpinner")
        self.spinner.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.message = QLabel(message)
        self.message.setObjectName("loadingText")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)

        self.subtext = QLabel("Please wait")
        self.subtext.setObjectName("loadingSubtext")
        self.subtext.setAlignment(Qt.AlignmentFlag.AlignCenter)

        root.addStretch(1)
        root.addWidget(self.logo, alignment=Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.spinner)
        root.addWidget(self.message)
        root.addWidget(self.subtext)
        root.addStretch(1)

        self._frame_index = 0
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(120)
        self._spin_timer.timeout.connect(self._advance_spinner)
        self._apply_theme()

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QDialog#loadingDialog {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0f1217,
                    stop:0.5 #161b24,
                    stop:1 #10151b
                );
                border: 1px solid #2a3240;
                border-radius: 16px;
            }
            QLabel#loadingLogo {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #23c965, stop:1 #193729);
                border-radius: 14px;
                color: #ffffff;
                font-size: 38px;
                font-weight: 800;
            }
            QLabel#loadingSpinner {
                color: #2de774;
                font-size: 22px;
                font-weight: 800;
            }
            QLabel#loadingText {
                color: #e8eef6;
                font-size: 14px;
                font-weight: 600;
            }
            QLabel#loadingSubtext {
                color: #9ba8b7;
                font-size: 12px;
            }
            """
        )

    def _advance_spinner(self) -> None:
        self._frame_index = (self._frame_index + 1) % len(self._SPINNER_FRAMES)
        self.spinner.setText(self._SPINNER_FRAMES[self._frame_index])

    def set_message(self, text: str) -> None:
        clean = text.strip() or "Loading..."
        self.message.setText(clean)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._center()
        if not self._spin_timer.isActive():
            self._spin_timer.start()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._spin_timer.stop()
        super().hideEvent(event)

    def _center(self) -> None:
        if self.parentWidget() is not None:
            parent_geo = self.parentWidget().frameGeometry()
            target = parent_geo.center() - self.rect().center()
            self.move(target)
            return
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(geo.center() - self.rect().center())


class DownloadThread(QThread):
    status = Signal(str)
    finished_files = Signal(list)
    failed = Signal(str)

    def __init__(self, url: str, output_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.url = url
        self.output_dir = output_dir

    def run(self) -> None:
        try:
            files = download_youtube_playlist(self.url, self.output_dir, self.status.emit)
            self.finished_files.emit([str(p) for p in files])
        except Exception as err:
            self.failed.emit(str(err))


class QueryDownloadThread(QThread):
    status = Signal(str)
    finished_files = Signal(list)
    failed = Signal(str)

    def __init__(self, queries: List[str], output_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.queries = queries
        self.output_dir = output_dir

    def run(self) -> None:
        try:
            files = download_youtube_queries(self.queries, self.output_dir, self.status.emit)
            self.finished_files.emit([str(p) for p in files])
        except Exception as err:
            self.failed.emit(str(err))


class SpotifyImportThread(QThread):
    status = Signal(str)
    finished_files = Signal(list, str)
    failed = Signal(str)

    def __init__(
        self,
        spotify_url: str,
        output_dir: Path,
        spotify_client_id: str,
        spotify_client_secret: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.spotify_url = spotify_url
        self.output_dir = output_dir
        self.spotify_client_id = spotify_client_id
        self.spotify_client_secret = spotify_client_secret

    def run(self) -> None:
        try:
            playlist_name, tracks = fetch_spotify_playlist_tracks(
                self.spotify_url,
                self.spotify_client_id,
                self.spotify_client_secret,
                progress_hook=self.status.emit,
            )
            queries = [track.search_query() for track in tracks]
            files = download_youtube_queries(queries, self.output_dir, self.status.emit)
            self.finished_files.emit([str(p) for p in files], playlist_name)
        except Exception as err:
            self.failed.emit(str(err))


class SearchThread(QThread):
    finished_results = Signal(list)
    failed = Signal(str)

    def __init__(self, query: str, limit: int = 12, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.query = query
        self.limit = limit

    def run(self) -> None:
        try:
            results = search_youtube_songs(self.query, self.limit)
            self.finished_results.emit(results)
        except Exception as err:
            self.failed.emit(str(err))


class LocalImportThread(QThread):
    status = Signal(str)
    finished_payload = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        source: str,
        folder_path: Path | None = None,
        recursive: bool = False,
        zip_path: Path | None = None,
        imports_dir: Path | None = None,
        saved_name: str | None = None,
        saved_paths: List[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.source = source
        self.folder_path = folder_path
        self.recursive = recursive
        self.zip_path = zip_path
        self.imports_dir = imports_dir
        self.saved_name = saved_name
        self.saved_paths = saved_paths or []

    @classmethod
    def for_folder(
        cls,
        folder_path: Path,
        recursive: bool,
        parent: QWidget | None = None,
    ) -> "LocalImportThread":
        return cls("folder", folder_path=folder_path, recursive=recursive, parent=parent)

    @classmethod
    def for_zip(
        cls,
        zip_path: Path,
        imports_dir: Path,
        parent: QWidget | None = None,
    ) -> "LocalImportThread":
        return cls("zip", zip_path=zip_path, imports_dir=imports_dir, parent=parent)

    @classmethod
    def for_saved_playlist(
        cls,
        name: str,
        paths: List[str],
        parent: QWidget | None = None,
    ) -> "LocalImportThread":
        return cls("saved", saved_name=name, saved_paths=paths, parent=parent)

    def run(self) -> None:
        try:
            if self.source == "folder":
                self._run_folder()
                return
            if self.source == "zip":
                self._run_zip()
                return
            if self.source == "saved":
                self._run_saved()
                return
            raise ValueError(f"Unsupported import source: {self.source}")
        except Exception as err:
            self.failed.emit(str(err))

    def _run_folder(self) -> None:
        if self.folder_path is None:
            raise ValueError("Missing folder path")
        folder = self.folder_path.expanduser()
        if not folder.exists() or not folder.is_dir():
            raise ValueError(f"Not a valid folder: {folder}")

        self.status.emit("Scanning folder for supported audio files...")
        songs = self._scan_audio_files(folder, recursive=self.recursive)
        if songs is None:
            return

        self.finished_payload.emit(
            {
                "mode": "folder",
                "songs": songs,
                "collection_name": folder.name or "Folder Import",
                "recursive": self.recursive,
            }
        )

    def _run_zip(self) -> None:
        if self.zip_path is None:
            raise ValueError("Missing ZIP path")
        if self.imports_dir is None:
            raise ValueError("Missing import destination directory")

        zip_path = self.zip_path.expanduser()
        if not zip_path.exists() or not zip_path.is_file():
            raise ValueError(f"Not a valid ZIP archive: {zip_path}")

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.imports_dir / f"{zip_path.stem}-{stamp}"
        target.mkdir(parents=True, exist_ok=True)

        self.status.emit(f"Extracting ZIP: {zip_path.name}")
        with zipfile.ZipFile(zip_path, "r") as archive:
            members = archive.infolist()
            total = len(members)
            for idx, member in enumerate(members, start=1):
                if self.isInterruptionRequested():
                    return
                self._safe_extract_member(archive, member.filename, target)
                if idx == 1 or idx % 25 == 0 or idx == total:
                    self.status.emit(f"Extracting ZIP entries... {idx}/{total}")

        self.status.emit("Indexing imported tracks...")
        songs = self._scan_audio_files(target, recursive=True)
        if songs is None:
            return

        self.finished_payload.emit(
            {
                "mode": "zip",
                "songs": songs,
                "collection_name": zip_path.stem or "ZIP Import",
                "target_dir": str(target),
            }
        )

    def _scan_audio_files(self, folder: Path, recursive: bool) -> List[str] | None:
        scanner = folder.rglob("*") if recursive else folder.iterdir()
        songs: List[str] = []
        scanned = 0

        for candidate in scanner:
            if self.isInterruptionRequested():
                return None

            scanned += 1
            if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTENSIONS:
                songs.append(str(candidate))

            if scanned == 1 or scanned % 350 == 0:
                self.status.emit(f"Scanning files... {scanned} checked, {len(songs)} tracks")

        songs.sort(key=str.lower)
        return songs

    def _run_saved(self) -> None:
        if not self.saved_name:
            raise ValueError("Missing saved playlist name")
        songs: List[str] = []
        checked = 0
        total = len(self.saved_paths)
        for raw in self.saved_paths:
            if self.isInterruptionRequested():
                return
            checked += 1
            path = Path(raw)
            if path.exists() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                songs.append(str(path))
            if checked == 1 or checked % 300 == 0 or checked == total:
                self.status.emit(f"Resolving saved playlist files... {checked}/{total}")

        self.finished_payload.emit(
            {
                "mode": "saved",
                "songs": songs,
                "collection_name": self.saved_name,
            }
        )

    @staticmethod
    def _safe_extract_member(archive: zipfile.ZipFile, member_name: str, target: Path) -> None:
        target_root = target.resolve()
        destination = (target / member_name).resolve()
        if target_root not in destination.parents and destination != target_root:
            raise ValueError(f"Unsafe path in ZIP archive: {member_name}")
        archive.extract(member_name, target)


class PlaylistMetadataThread(QThread):
    status = Signal(str)
    song_ready = Signal(int, str, object, object)
    batch_finished = Signal(int)
    failed = Signal(int, str)

    def __init__(self, generation: int, songs: List[Path], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.generation = generation
        self.songs = songs

    def run(self) -> None:
        total = len(self.songs)
        try:
            for idx, song in enumerate(self.songs, start=1):
                if self.isInterruptionRequested():
                    return
                key = self._song_key(song)
                metadata = read_audio_metadata(song)
                art_bytes = read_album_art_bytes(song)
                self.song_ready.emit(self.generation, key, metadata, art_bytes)
                if idx == 1 or idx % 8 == 0 or idx == total:
                    self.status.emit(f"Loading metadata... {idx}/{total}")
            self.batch_finished.emit(self.generation)
        except Exception as err:
            self.failed.emit(self.generation, str(err))

    @staticmethod
    def _song_key(song: Path) -> str:
        try:
            return str(song.resolve())
        except Exception:
            return str(song)


class SettingsDialog(QDialog):
    def __init__(self, settings: SettingsManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setObjectName("settingsDialog")
        self.setWindowTitle("Sabrinth Settings")
        self.resize(620, 470)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        title = QLabel("Settings")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Playback, library, and import behavior")
        subtitle.setObjectName("dialogSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        root.addLayout(form)

        self.theme_combo = QComboBox()
        self.theme_combo.setView(QListView())
        for label, value in THEME_OPTIONS.items():
            self.theme_combo.addItem(label, value)
        current_theme = settings.get_str("theme")
        idx = self.theme_combo.findData(current_theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        form.addRow("Theme", self.theme_combo)

        self.default_volume = QSpinBox()
        self.default_volume.setRange(0, 100)
        self.default_volume.setValue(settings.get_int("default_volume"))
        form.addRow("Default volume", self.default_volume)

        self.shuffle_on_load = QCheckBox("Shuffle when loading folders and imports")
        self.shuffle_on_load.setChecked(settings.get_bool("shuffle_on_load"))
        form.addRow("Shuffle on load", self.shuffle_on_load)

        self.autoplay_on_load = QCheckBox("Start playback automatically after loading")
        self.autoplay_on_load.setChecked(settings.get_bool("autoplay_on_load"))
        form.addRow("Autoplay", self.autoplay_on_load)

        self.recursive_scan = QCheckBox("Scan subfolders recursively")
        self.recursive_scan.setChecked(settings.get_bool("recursive_scan"))
        form.addRow("Recursive scan", self.recursive_scan)

        self.show_track_stats = QCheckBox("Show started/played/skipped stats in playlist")
        self.show_track_stats.setChecked(settings.get_bool("show_track_stats"))
        form.addRow("Track stats", self.show_track_stats)

        self.auto_adjust_enabled = QCheckBox("Enable dynamic volume mode by default")
        self.auto_adjust_enabled.setChecked(settings.get_bool("auto_adjust_enabled"))
        form.addRow("Dynamic volume", self.auto_adjust_enabled)

        self.use_default_download_dir = QCheckBox("Always use configured download directory")
        self.use_default_download_dir.setChecked(settings.get_bool("use_default_download_dir"))
        form.addRow("Download behavior", self.use_default_download_dir)

        download_row = QHBoxLayout()
        self.download_dir_input = QLineEdit(settings.get_str("download_dir"))
        self.download_browse_btn = QPushButton("Browse")
        self.download_browse_btn.clicked.connect(self._browse_download_dir)
        download_row.addWidget(self.download_dir_input, stretch=1)
        download_row.addWidget(self.download_browse_btn)
        form.addRow("Download directory", download_row)

        self.spotify_client_id_input = QLineEdit(settings.get_str("spotify_client_id"))
        self.spotify_client_id_input.setPlaceholderText("Spotify Client ID")
        form.addRow("Spotify client ID", self.spotify_client_id_input)

        self.spotify_client_secret_input = QLineEdit(settings.get_str("spotify_client_secret"))
        self.spotify_client_secret_input.setPlaceholderText("Spotify Client Secret")
        self.spotify_client_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Spotify client secret", self.spotify_client_secret_input)

        self.use_default_download_dir.toggled.connect(self._on_download_mode_changed)
        self._on_download_mode_changed(self.use_default_download_dir.isChecked())

        root.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        save_btn.setText("Save")
        save_btn.setObjectName("saveBtn")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._apply_dialog_theme()

    def _apply_dialog_theme(self) -> None:
        self.setStyleSheet(
            """
            QDialog#settingsDialog {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0f1013,
                    stop:0.45 #15181d,
                    stop:1 #111318
                );
                color: #e8edf3;
            }
            QLabel#dialogTitle {
                color: #ffffff;
                font-size: 26px;
                font-weight: 700;
            }
            QLabel#dialogSubtitle {
                color: #9aa6b3;
                font-size: 13px;
                margin-bottom: 6px;
            }
            QLineEdit, QComboBox, QSpinBox {
                background: #101217;
                color: #f0f5fb;
                border: 1px solid #2f3742;
                border-radius: 10px;
                padding: 8px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 1px solid #2de674;
            }
            QCheckBox {
                color: #d1d9e2;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #3a4654;
                background: #0d0f14;
            }
            QCheckBox::indicator:checked {
                background: #21c863;
                border: 1px solid #2ee876;
            }
            QPushButton {
                color: #ebf1f7;
                border: 1px solid #364251;
                border-radius: 10px;
                background: #171b22;
                padding: 8px 12px;
            }
            QPushButton:hover { border-color: #2fe978; }
            QDialogButtonBox QPushButton {
                min-width: 96px;
                font-weight: 600;
            }
            QPushButton#saveBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #23ca64, stop:1 #1ca654);
                border: 1px solid #2ee977;
                color: #ffffff;
            }
            """
        )

    def _browse_download_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose Download Directory")
        if chosen:
            self.download_dir_input.setText(chosen)

    def _on_download_mode_changed(self, checked: bool) -> None:
        self.download_dir_input.setEnabled(checked)
        self.download_browse_btn.setEnabled(checked)

    def values(self) -> Dict[str, object]:
        theme = self.theme_combo.currentData()
        return {
            "theme": str(theme),
            "default_volume": self.default_volume.value(),
            "shuffle_on_load": self.shuffle_on_load.isChecked(),
            "autoplay_on_load": self.autoplay_on_load.isChecked(),
            "recursive_scan": self.recursive_scan.isChecked(),
            "show_track_stats": self.show_track_stats.isChecked(),
            "auto_adjust_enabled": self.auto_adjust_enabled.isChecked(),
            "use_default_download_dir": self.use_default_download_dir.isChecked(),
            "download_dir": self.download_dir_input.text().strip() or str(
                self._settings.app_dir / "downloads"
            ),
            "spotify_client_id": self.spotify_client_id_input.text().strip(),
            "spotify_client_secret": self.spotify_client_secret_input.text().strip(),
        }


class ImportDialog(QDialog):
    def __init__(self, default_download_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import")
        self.resize(600, 340)

        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)

        self.source_combo = QComboBox()
        self.source_combo.addItem("Folder", "folder")
        self.source_combo.addItem("ZIP Archive", "zip")
        self.source_combo.addItem("Spotify Playlist", "spotify")
        self.source_combo.addItem("YouTube Playlist", "youtube")
        form.addRow("Source", self.source_combo)

        self.folder_row = QWidget()
        folder_layout = QHBoxLayout(self.folder_row)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("Choose a music folder")
        self.folder_browse_btn = QPushButton("Browse")
        self.folder_browse_btn.clicked.connect(self._browse_folder)
        folder_layout.addWidget(self.folder_input, stretch=1)
        folder_layout.addWidget(self.folder_browse_btn)
        form.addRow("Folder", self.folder_row)

        self.zip_row = QWidget()
        zip_layout = QHBoxLayout(self.zip_row)
        zip_layout.setContentsMargins(0, 0, 0, 0)
        self.zip_input = QLineEdit()
        self.zip_input.setPlaceholderText("Choose ZIP archive")
        self.zip_browse_btn = QPushButton("Browse")
        self.zip_browse_btn.clicked.connect(self._browse_zip)
        zip_layout.addWidget(self.zip_input, stretch=1)
        zip_layout.addWidget(self.zip_browse_btn)
        form.addRow("ZIP", self.zip_row)

        self.spotify_row = QWidget()
        spotify_layout = QVBoxLayout(self.spotify_row)
        spotify_layout.setContentsMargins(0, 0, 0, 0)
        spotify_layout.setSpacing(6)
        self.spotify_input = QLineEdit()
        self.spotify_input.setPlaceholderText("Paste Spotify playlist URL")
        self.spotify_hint = QLabel("Public playlists work best. Set Spotify API credentials in Settings.")
        self.spotify_hint.setObjectName("meta")
        self.spotify_hint.setWordWrap(True)
        spotify_layout.addWidget(self.spotify_input)
        spotify_layout.addWidget(self.spotify_hint)
        form.addRow("Spotify", self.spotify_row)

        self.youtube_row = QWidget()
        youtube_layout = QVBoxLayout(self.youtube_row)
        youtube_layout.setContentsMargins(0, 0, 0, 0)
        youtube_layout.setSpacing(6)
        self.youtube_input = QLineEdit()
        self.youtube_input.setPlaceholderText("Paste YouTube playlist URL")
        self.youtube_hint = QLabel(f"Downloads go to: {default_download_dir}")
        self.youtube_hint.setObjectName("meta")
        self.youtube_hint.setWordWrap(True)
        youtube_layout.addWidget(self.youtube_input)
        youtube_layout.addWidget(self.youtube_hint)
        form.addRow("YouTube", self.youtube_row)

        self.source_combo.currentIndexChanged.connect(self._sync_rows)
        self._sync_rows()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose audio folder")
        if path:
            self.folder_input.setText(path)

    def _browse_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose ZIP archive", "", "ZIP Archives (*.zip)")
        if path:
            self.zip_input.setText(path)

    def _sync_rows(self) -> None:
        source = str(self.source_combo.currentData())
        self.folder_row.setVisible(source == "folder")
        self.zip_row.setVisible(source == "zip")
        self.spotify_row.setVisible(source == "spotify")
        self.youtube_row.setVisible(source == "youtube")

    def payload(self) -> tuple[str, str]:
        source = str(self.source_combo.currentData())
        if source == "folder":
            return source, self.folder_input.text().strip()
        if source == "zip":
            return source, self.zip_input.text().strip()
        if source == "spotify":
            return source, self.spotify_input.text().strip()
        return source, self.youtube_input.text().strip()


class SongSearchDialog(QDialog):
    def __init__(self, initial_query: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("songSearchDialog")
        self.setWindowTitle("Find Songs")
        self.resize(860, 560)
        self._search_thread: SearchThread | None = None
        self._results: List[YouTubeSearchResult] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title = QLabel("Find Songs")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Search YouTube, pick tracks, and build your queue.")
        subtitle.setObjectName("dialogSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        query_row = QHBoxLayout()
        self.query_input = QLineEdit(initial_query)
        self.query_input.setPlaceholderText("Search songs, artists, albums...")
        self.search_btn = QPushButton("Search")
        self.search_btn.setObjectName("searchBtn")
        query_row.addWidget(self.query_input, stretch=1)
        query_row.addWidget(self.search_btn)
        root.addLayout(query_row)

        self.results_table = QTreeWidget()
        self.results_table.setObjectName("searchResults")
        self.results_table.setColumnCount(3)
        self.results_table.setHeaderLabels(["Title", "Channel", "Time"])
        self.results_table.setRootIsDecorated(False)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.setUniformRowHeights(True)
        self.results_table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self.results_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        search_header = self.results_table.header()
        search_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        search_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        search_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.results_table.setColumnWidth(2, 72)
        root.addWidget(self.results_table, stretch=1)

        options_form = QFormLayout()
        options_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.replace_queue_checkbox = QCheckBox("Replace current queue with downloaded results")
        options_form.addRow("Queue", self.replace_queue_checkbox)
        self.save_playlist_name = QLineEdit()
        self.save_playlist_name.setPlaceholderText("Optional saved playlist name after download")
        options_form.addRow("Save As", self.save_playlist_name)
        root.addLayout(options_form)

        self.status_label = QLabel("Search and select songs to download.")
        self.status_label.setObjectName("meta")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        add_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        add_btn.setText("Download Selected")
        add_btn.setObjectName("runBtn")
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.search_btn.clicked.connect(self._start_search)
        self.query_input.returnPressed.connect(self._start_search)
        self._apply_dialog_theme()

    def _apply_dialog_theme(self) -> None:
        self.setStyleSheet(
            """
            QDialog#songSearchDialog {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #101218,
                    stop:0.55 #171a22,
                    stop:1 #12151d
                );
                color: #e7edf5;
            }
            QLabel#dialogTitle {
                color: #ffffff;
                font-size: 24px;
                font-weight: 700;
            }
            QLabel#dialogSubtitle {
                color: #95a2b1;
                font-size: 13px;
            }
            QLineEdit, QComboBox {
                background: #0f131a;
                border: 1px solid #2f3a4a;
                border-radius: 10px;
                color: #edf3fb;
                padding: 8px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #2ee876;
            }
            QTreeWidget#searchResults {
                background: #0e1118;
                border: 1px solid #2b3544;
                border-radius: 12px;
                color: #e2eaf3;
            }
            QTreeWidget#searchResults::item {
                padding: 8px 6px;
            }
            QTreeWidget#searchResults::item:selected {
                background: #1f3b2d;
                color: #ffffff;
            }
            QHeaderView::section {
                background: #151a23;
                color: #9aa8b7;
                border: none;
                border-bottom: 1px solid #2e3a49;
                padding: 8px 10px;
                font-size: 11px;
                font-weight: 700;
                text-transform: uppercase;
            }
            QCheckBox {
                color: #d4dde7;
            }
            QPushButton {
                color: #ecf3fb;
                border: 1px solid #374456;
                border-radius: 10px;
                background: #18202a;
                padding: 8px 12px;
            }
            QPushButton#searchBtn, QPushButton#runBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #24c965, stop:1 #1ca454);
                border: 1px solid #2ee877;
                color: #ffffff;
                font-weight: 700;
            }
            """
        )

    def _start_search(self) -> None:
        query = self.query_input.text().strip()
        if not query:
            self.status_label.setText("Enter a query first.")
            return
        if self._search_thread and self._search_thread.isRunning():
            return

        self.status_label.setText(f"Searching for '{query}'...")
        self.search_btn.setEnabled(False)
        self.results_table.clear()
        self._results.clear()

        self._search_thread = SearchThread(query, limit=15, parent=self)
        self._search_thread.finished_results.connect(self._on_search_results)
        self._search_thread.failed.connect(self._on_search_failed)
        self._search_thread.finished.connect(lambda: self.search_btn.setEnabled(True))
        self._search_thread.start()

    def _on_search_results(self, results: List[YouTubeSearchResult]) -> None:
        self._results = results
        self.results_table.clear()
        for idx, result in enumerate(results):
            item = QTreeWidgetItem([result.title, result.channel, result.duration_text()])
            item.setData(0, Qt.ItemDataRole.UserRole, idx)
            if result.webpage_url:
                item.setToolTip(0, result.webpage_url)
            self.results_table.addTopLevelItem(item)
        if not results:
            self.status_label.setText("No results found. Try a different query.")
            return
        self.status_label.setText(f"Found {len(results)} results. Select songs to add.")

    def _on_search_failed(self, message: str) -> None:
        self.status_label.setText(f"Search failed: {message}")

    def _selected_queries(self) -> List[str]:
        queries: List[str] = []
        for item in self.results_table.selectedItems():
            idx = item.data(0, Qt.ItemDataRole.UserRole)
            if idx is None:
                continue
            try:
                result = self._results[int(idx)]
            except (TypeError, ValueError, IndexError):
                continue
            queries.append(result.query_hint)
        return queries

    def _accept_if_valid(self) -> None:
        if not self._selected_queries():
            QMessageBox.information(self, "No Songs Selected", "Select at least one search result.")
            return
        self.accept()

    def payload(self) -> tuple[List[str], bool, str]:
        save_name = " ".join(self.save_playlist_name.text().strip().split())
        return self._selected_queries(), self.replace_queue_checkbox.isChecked(), save_name

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._search_thread and self._search_thread.isRunning():
            self.status_label.setText("Search in progress. Please wait for completion before closing.")
            event.ignore()
            return
        super().closeEvent(event)


class LibraryDialog(QDialog):
    def __init__(self, saved_playlists: dict[str, int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._saved_playlists = saved_playlists
        self.setObjectName("libraryDialog")
        self.setWindowTitle("Library")
        self.resize(640, 430)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title = QLabel("Library")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Saved profiles and queue actions")
        subtitle.setObjectName("dialogSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        root.addLayout(form)

        self.action_combo = QComboBox()
        self.action_combo.setView(QListView())
        self.action_combo.addItem("Save Current Playlist", "save")
        self.action_combo.addItem("Load Saved Playlist", "load")
        self.action_combo.addItem("Delete Saved Playlist", "delete")
        self.action_combo.addItem("Shuffle Playlist", "shuffle")
        form.addRow("Action", self.action_combo)

        self.name_input = QLineEdit()
        form.addRow("Value", self.name_input)

        self.saved_combo = QComboBox()
        self.saved_combo.setView(QListView())
        self.saved_combo.addItem("Select saved playlist...", "")
        for name in sorted(saved_playlists.keys(), key=str.lower):
            self.saved_combo.addItem(name, name)
        form.addRow("Saved", self.saved_combo)

        saved_label = QLabel("All Saved Profiles")
        saved_label.setObjectName("sectionTitle")
        root.addWidget(saved_label)

        self.saved_list = QListWidget()
        self.saved_list.setObjectName("savedProfileList")
        self._populate_saved_list()
        root.addWidget(self.saved_list, stretch=1)

        self.action_combo.currentIndexChanged.connect(self._sync_fields)
        self.saved_list.itemSelectionChanged.connect(self._sync_saved_combo)
        self._sync_fields()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        run_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        run_btn.setText("Run")
        run_btn.setObjectName("runBtn")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._apply_dialog_theme()

    def _apply_dialog_theme(self) -> None:
        self.setStyleSheet(
            """
            QDialog#libraryDialog {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #101216,
                    stop:0.55 #171821,
                    stop:1 #12141a
                );
                color: #e7edf4;
            }
            QLabel#dialogTitle {
                color: #ffffff;
                font-size: 24px;
                font-weight: 700;
            }
            QLabel#dialogSubtitle {
                color: #95a3b2;
                font-size: 13px;
                margin-bottom: 6px;
            }
            QLabel#sectionTitle {
                color: #adbac9;
                font-size: 12px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            QLineEdit, QComboBox {
                background: #10131a;
                color: #edf3f9;
                border: 1px solid #303949;
                border-radius: 10px;
                padding: 8px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #2de675;
            }
            QListWidget#savedProfileList {
                background: #0f1219;
                border: 1px solid #2e3847;
                border-radius: 12px;
                color: #dee6ef;
                outline: none;
            }
            QListWidget#savedProfileList::item {
                padding: 9px 12px;
                margin: 2px 4px;
                border-radius: 8px;
            }
            QListWidget#savedProfileList::item:selected {
                background: #1f3b2d;
                color: #ffffff;
            }
            QPushButton {
                color: #ebf2f8;
                border: 1px solid #364152;
                border-radius: 10px;
                background: #191e26;
                padding: 8px 12px;
            }
            QPushButton#runBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #23ca64, stop:1 #1ca555);
                border: 1px solid #2ee876;
                color: #ffffff;
                font-weight: 700;
            }
            """
        )

    def _populate_saved_list(self) -> None:
        self.saved_list.clear()
        if not self._saved_playlists:
            placeholder = QListWidgetItem("No saved playlists yet")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.saved_list.addItem(placeholder)
            return

        for name in sorted(self._saved_playlists.keys(), key=str.lower):
            count = self._saved_playlists.get(name, 0)
            item = QListWidgetItem(f"{name}  ·  {count} tracks")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.saved_list.addItem(item)

    def _sync_saved_combo(self) -> None:
        item = self.saved_list.currentItem()
        if not item:
            return
        name = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not name:
            return
        idx = self.saved_combo.findData(name)
        if idx >= 0:
            self.saved_combo.setCurrentIndex(idx)

    def _sync_fields(self) -> None:
        action = str(self.action_combo.currentData())
        needs_name = action in {"save", "shuffle"}
        needs_saved = action in {"load", "delete"}

        self.name_input.setVisible(needs_name)
        self.saved_combo.setVisible(needs_saved)

        if action == "save":
            self.name_input.setPlaceholderText("Playlist name")
        elif action == "shuffle":
            self.name_input.setPlaceholderText("Seed (blank = random)")

    def payload(self) -> tuple[str, str]:
        action = str(self.action_combo.currentData())
        if action in {"load", "delete"}:
            value = str(self.saved_combo.currentData() or "").strip()
        else:
            value = self.name_input.text().strip()
        return action, value


class DebugDialog(QDialog):
    def __init__(self, snapshot_getter: Callable[[], str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._snapshot_getter = snapshot_getter
        self.setObjectName("debugDialog")
        self.setWindowTitle("Debug Panel")
        self.resize(760, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title = QLabel("Debug Panel")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Runtime state for troubleshooting")
        subtitle.setObjectName("dialogSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        self.output = QPlainTextEdit()
        self.output.setObjectName("debugOutput")
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        root.addWidget(self.output, stretch=1)

        buttons = QDialogButtonBox()
        refresh_btn = buttons.addButton("Refresh", QDialogButtonBox.ButtonRole.ActionRole)
        close_btn = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        refresh_btn.clicked.connect(self.refresh)
        close_btn.clicked.connect(self.accept)
        root.addWidget(buttons)

        self._apply_dialog_theme()
        self.refresh()

    def _apply_dialog_theme(self) -> None:
        self.setStyleSheet(
            """
            QDialog#debugDialog {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0e1116,
                    stop:0.5 #141923,
                    stop:1 #10141c
                );
                color: #e6edf5;
            }
            QLabel#dialogTitle {
                color: #ffffff;
                font-size: 24px;
                font-weight: 700;
            }
            QLabel#dialogSubtitle {
                color: #93a1b1;
                font-size: 13px;
                margin-bottom: 6px;
            }
            QPlainTextEdit#debugOutput {
                background: #0b0f14;
                border: 1px solid #2c3646;
                border-radius: 12px;
                color: #dbe6f2;
                selection-background-color: #244d36;
                selection-color: #ffffff;
                padding: 10px;
                font-family: "JetBrains Mono", "Cascadia Mono", monospace;
                font-size: 12px;
            }
            QPushButton {
                color: #ecf3fb;
                border: 1px solid #384457;
                border-radius: 10px;
                background: #19212b;
                padding: 8px 14px;
            }
            QPushButton:hover { border-color: #2ce573; }
            """
        )

    def refresh(self) -> None:
        self.output.setPlainText(self._snapshot_getter())


class MainWindow(QMainWindow):
    track_finished_signal = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.settings = SettingsManager()

        self.setWindowTitle("Sabrinth Player")
        self.resize(1240, 760)
        if LOGO_PATH.exists():
            self.setWindowIcon(QIcon(str(LOGO_PATH)))

        self.playlist_manager = PlaylistManager()
        self.player = AudioPlayer(on_track_end=self.track_finished_signal.emit)

        self.track_duration = 0.0
        self.slider_dragging = False
        self.auto_adjust_enabled = self.settings.get_bool("auto_adjust_enabled")
        self.next_adjust_at = 0.0
        self.download_thread: DownloadThread | None = None
        self.query_download_thread: QueryDownloadThread | None = None
        self.spotify_thread: SpotifyImportThread | None = None
        self.local_import_thread: LocalImportThread | None = None
        self.metadata_thread: PlaylistMetadataThread | None = None
        self._metadata_workers: List[PlaylistMetadataThread] = []
        self.loading_dialog: LoadingDialog | None = None
        self.theme_name = self.settings.get_str("theme")
        if self.theme_name not in THEME_OPTIONS.values():
            self.theme_name = "pitch_black"

        self._logo_phase = 0.0
        self._metadata_generation = 0
        self._playlist_row_lookup: Dict[str, QTreeWidgetItem] = {}
        self._metadata_cache: Dict[str, AudioMetadata] = {}
        self._art_cache: Dict[str, QPixmap | None] = {}
        self.active_collection_name = "Your Queue"

        self._build_ui()
        self._build_menu()
        self._setup_shortcuts()
        self._connect_events()

        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(250)
        self.progress_timer.timeout.connect(self._update_progress)
        self.progress_timer.start()

        self.logo_timer = QTimer(self)
        self.logo_timer.setInterval(85)
        self.logo_timer.timeout.connect(self._animate_logo_glow)
        self.logo_timer.start()

        self.track_finished_signal.connect(self._on_track_finished)

        self.volume_slider.setValue(self.settings.get_int("default_volume"))
        self._update_auto_button()
        self._apply_theme()
        self._refresh_download_hint()
        self._refresh_playlist_view()
        self._refresh_saved_playlist_combo()

    def _build_menu(self) -> None:
        app_menu = self.menuBar().addMenu("Sabrinth")
        debug_menu = self.menuBar().addMenu("Debug")

        settings_action = QAction("Settings", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self.open_settings)

        search_action = QAction("Find Songs", self)
        search_action.setShortcut(QKeySequence("Ctrl+K"))
        search_action.triggered.connect(self.open_song_search)

        spotify_import_action = QAction("Import Spotify Playlist", self)
        spotify_import_action.triggered.connect(self._prompt_spotify_import)

        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)

        app_menu.addAction(search_action)
        app_menu.addAction(spotify_import_action)
        app_menu.addSeparator()
        app_menu.addAction(settings_action)
        app_menu.addSeparator()
        app_menu.addAction(quit_action)

        debug_panel_action = QAction("Open Debug Panel", self)
        debug_panel_action.setShortcut(QKeySequence("Ctrl+Shift+D"))
        debug_panel_action.triggered.connect(self.open_debug_panel)

        refresh_meta_action = QAction("Refresh Metadata Cache", self)
        refresh_meta_action.triggered.connect(self.refresh_metadata_cache)

        debug_menu.addAction(debug_panel_action)
        debug_menu.addAction(refresh_meta_action)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.setSpacing(12)

        self.logo_label = QLabel()
        self.logo_label.setObjectName("logo")
        self.logo_label.setFixedSize(42, 42)
        if LOGO_PATH.exists():
            pix = QPixmap(str(LOGO_PATH))
            if not pix.isNull():
                self.logo_label.setPixmap(
                    pix.scaled(
                        42,
                        42,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )

        self.logo_glow = QGraphicsDropShadowEffect(self.logo_label)
        self.logo_glow.setOffset(0, 0)
        self.logo_glow.setBlurRadius(18)
        self.logo_glow.setColor(QColor(255, 255, 255, 125))
        self.logo_label.setGraphicsEffect(self.logo_glow)

        logo_wrap = QHBoxLayout()
        logo_wrap.setSpacing(10)
        logo_wrap.addWidget(self.logo_label)

        branding = QVBoxLayout()
        branding.setSpacing(1)
        title = QLabel("Sabrinth Player")
        title.setObjectName("title")
        subtitle = QLabel("Dark stream deck")
        subtitle.setObjectName("subtitle")
        branding.addWidget(title)
        branding.addWidget(subtitle)
        logo_wrap.addLayout(branding)

        search_wrap = QFrame()
        search_wrap.setObjectName("searchContainer")
        search_layout = QHBoxLayout(search_wrap)
        search_layout.setContentsMargins(10, 6, 10, 6)
        search_layout.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("What do you want to play?")
        search_layout.addWidget(self.search_input)

        self.import_btn = QPushButton("Import")
        self.import_btn.setObjectName("primaryBtn")
        self.import_btn.setToolTip("Import from folder, ZIP archive, Spotify playlist, or YouTube playlist")
        self.find_songs_btn = QPushButton("Find Songs")
        self.find_songs_btn.setObjectName("ghostBtn")
        self.find_songs_btn.setToolTip("Search songs and add them to your queue")
        self.library_btn = QPushButton("Library")
        self.library_btn.setObjectName("ghostBtn")
        self.library_btn.setToolTip("Save, load, delete, or shuffle playlists")
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setObjectName("ghostBtn")
        self.settings_btn.setFixedWidth(46)

        header_layout.addLayout(logo_wrap)
        header_layout.addStretch(1)
        header_layout.addWidget(search_wrap, stretch=4)
        header_layout.addWidget(self.import_btn)
        header_layout.addWidget(self.find_songs_btn)
        header_layout.addWidget(self.library_btn)
        header_layout.addWidget(self.settings_btn)

        outer.addWidget(header)

        body = QFrame()
        body.setObjectName("body")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(12)

        nav_rail = QFrame()
        nav_rail.setObjectName("navRail")
        nav_rail.setFixedWidth(68)
        nav_layout = QVBoxLayout(nav_rail)
        nav_layout.setContentsMargins(10, 12, 10, 12)
        nav_layout.setSpacing(10)
        self.rail_home_btn = QPushButton("⌂")
        self.rail_home_btn.setObjectName("railBtn")
        self.rail_library_btn = QPushButton("♫")
        self.rail_library_btn.setObjectName("railBtn")
        self.rail_saved_btn = QPushButton("❤")
        self.rail_saved_btn.setObjectName("railBtn")
        for btn in (self.rail_home_btn, self.rail_library_btn, self.rail_saved_btn):
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setMinimumHeight(36)
            nav_layout.addWidget(btn)
        self.rail_home_btn.setChecked(True)
        nav_layout.addStretch(1)
        body_layout.addWidget(nav_rail)

        center_pane = QFrame()
        center_pane.setObjectName("centerPane")
        center_layout = QVBoxLayout(center_pane)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(10)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        for idx, label in enumerate(("All", "Music", "Playlists", "Downloads")):
            chip = QPushButton(label)
            chip.setObjectName("chipBtn")
            chip.setCheckable(True)
            chip.setChecked(idx == 0)
            chip_row.addWidget(chip)
        chip_row.addStretch(1)
        center_layout.addLayout(chip_row)

        hero_card = QFrame()
        hero_card.setObjectName("heroCard")
        hero_layout = QHBoxLayout(hero_card)
        hero_layout.setContentsMargins(16, 16, 16, 16)
        hero_layout.setSpacing(16)
        self.hero_art = QLabel("♪")
        self.hero_art.setObjectName("heroArt")
        self.hero_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_art.setFixedSize(118, 118)

        hero_text_col = QVBoxLayout()
        hero_text_col.setSpacing(2)
        self.hero_context = QLabel("Playlist")
        self.hero_context.setObjectName("heroContext")
        self.hero_title = QLabel("Your Queue")
        self.hero_title.setObjectName("heroTitle")
        self.hero_subtitle = QLabel("0 songs")
        self.hero_subtitle.setObjectName("heroSubtitle")
        hero_text_col.addWidget(self.hero_context)
        hero_text_col.addWidget(self.hero_title)
        hero_text_col.addWidget(self.hero_subtitle)
        hero_text_col.addStretch(1)

        hero_layout.addWidget(self.hero_art)
        hero_layout.addLayout(hero_text_col, stretch=1)
        center_layout.addWidget(hero_card)

        playlist_panel = QFrame()
        playlist_panel.setObjectName("playlistPanel")
        playlist_layout = QVBoxLayout(playlist_panel)
        playlist_layout.setContentsMargins(14, 14, 14, 14)
        playlist_layout.setSpacing(8)
        top_row = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        playlist_label = QLabel("Queue / Library")
        playlist_label.setObjectName("sectionTitle")
        self.playlist_count_label = QLabel("0 tracks")
        self.playlist_count_label.setObjectName("meta")
        title_col.addWidget(playlist_label)
        title_col.addWidget(self.playlist_count_label)
        top_row.addLayout(title_col)
        top_row.addStretch(1)
        self.hero_play_btn = QPushButton("▶ Play")
        self.hero_play_btn.setObjectName("heroPlayBtn")
        self.hero_play_btn.setToolTip("Play current queue")
        top_row.addWidget(self.hero_play_btn)
        playlist_layout.addLayout(top_row)
        self.playlist_table = QTreeWidget()
        self.playlist_table.setObjectName("playlistTable")
        self.playlist_table.setColumnCount(6)
        self.playlist_table.setHeaderLabels(["#", "Title", "Artist", "Album", "Added", "Time"])
        self.playlist_table.setRootIsDecorated(False)
        self.playlist_table.setUniformRowHeights(True)
        self.playlist_table.setIconSize(QSize(40, 40))
        self.playlist_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.playlist_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.playlist_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.playlist_table.setIndentation(0)
        self.playlist_table.setAlternatingRowColors(False)
        self.playlist_table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self.playlist_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.playlist_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = self.playlist_table.header()
        header.setSectionsClickable(False)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.playlist_table.setColumnWidth(0, 54)
        self.playlist_table.setColumnWidth(4, 118)
        self.playlist_table.setColumnWidth(5, 74)
        playlist_layout.addWidget(self.playlist_table, stretch=1)
        center_layout.addWidget(playlist_panel, stretch=1)

        saved_panel = QFrame()
        saved_panel.setObjectName("savedPanel")
        saved_layout = QVBoxLayout(saved_panel)
        saved_layout.setContentsMargins(12, 12, 12, 12)
        saved_layout.setSpacing(8)
        saved_top_row = QHBoxLayout()
        saved_title = QLabel("Saved Playlists")
        saved_title.setObjectName("sectionTitle")
        self.saved_count_label = QLabel("0")
        self.saved_count_label.setObjectName("meta")
        self.saved_view_all_btn = QPushButton("View All")
        self.saved_view_all_btn.setObjectName("ghostBtn")
        saved_top_row.addWidget(saved_title)
        saved_top_row.addWidget(self.saved_count_label)
        saved_top_row.addStretch(1)
        saved_top_row.addWidget(self.saved_view_all_btn)
        saved_layout.addLayout(saved_top_row)

        self.saved_home_list = QListWidget()
        self.saved_home_list.setObjectName("savedHomeList")
        self.saved_home_list.setViewMode(QListView.ViewMode.IconMode)
        self.saved_home_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.saved_home_list.setMovement(QListView.Movement.Static)
        self.saved_home_list.setFlow(QListView.Flow.LeftToRight)
        self.saved_home_list.setWrapping(False)
        self.saved_home_list.setWordWrap(True)
        self.saved_home_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.saved_home_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.saved_home_list.setGridSize(QSize(188, 88))
        self.saved_home_list.setIconSize(QSize(46, 46))
        self.saved_home_list.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        saved_layout.addWidget(self.saved_home_list)
        center_layout.addWidget(saved_panel)

        self.download_dir_hint = QLabel("")
        self.download_dir_hint.setObjectName("meta")
        self.download_dir_hint.setWordWrap(True)
        center_layout.addWidget(self.download_dir_hint)
        body_layout.addWidget(center_pane, stretch=4)

        right_panel = QFrame()
        right_panel.setObjectName("rightPanel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(12)

        now_label = QLabel("Now Playing")
        now_label.setObjectName("sectionTitle")
        right_layout.addWidget(now_label)

        self.now_playing = QLabel("No track loaded")
        self.now_playing.setObjectName("nowPlaying")

        self.meta_label = QLabel("Load a folder, ZIP archive, or playlist to start")
        self.meta_label.setObjectName("meta")
        self.meta_label.setWordWrap(True)

        self.path_label = QLabel("-")
        self.path_label.setObjectName("path")
        self.path_label.setWordWrap(True)

        right_layout.addWidget(self.now_playing)
        right_layout.addWidget(self.meta_label)
        right_layout.addWidget(self.path_label)
        art_card = QFrame()
        art_card.setObjectName("artCard")
        art_layout = QVBoxLayout(art_card)
        art_layout.setContentsMargins(14, 14, 14, 14)
        art_layout.setSpacing(8)
        art_title = QLabel("Album Art")
        art_title.setObjectName("sectionTitle")
        self.artwork_label = QLabel()
        self.artwork_label.setObjectName("artworkLarge")
        self.artwork_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artwork_label.setFixedSize(272, 272)
        art_text = QLabel("Artwork, artist, and metadata preview.")
        art_text.setObjectName("meta")
        art_text.setWordWrap(True)
        art_layout.addWidget(art_title)
        art_layout.addWidget(self.artwork_label, alignment=Qt.AlignmentFlag.AlignCenter)
        art_layout.addWidget(art_text)
        right_layout.addWidget(art_card)
        right_layout.addStretch(1)
        body_layout.addWidget(right_panel, stretch=2)

        outer.addWidget(body, stretch=1)

        player_bar = QFrame()
        player_bar.setObjectName("playerBar")
        player_layout = QVBoxLayout(player_bar)
        player_layout.setContentsMargins(16, 10, 16, 10)
        player_layout.setSpacing(8)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(8)
        self.prev_btn = QPushButton("⏮")
        self.play_btn = QPushButton("Play")
        self.next_btn = QPushButton("⏭")
        for btn in (self.prev_btn, self.play_btn, self.next_btn):
            btn.setObjectName("controlBtn")
            controls_row.addWidget(btn)

        self.time_current = QLabel("0:00")
        self.time_total = QLabel("0:00")
        self.time_current.setObjectName("time")
        self.time_total.setObjectName("time")
        controls_row.addSpacing(8)
        controls_row.addWidget(self.time_current)

        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 1000)
        controls_row.addWidget(self.progress_slider, stretch=1)
        controls_row.addWidget(self.time_total)

        controls_row.addSpacing(10)
        volume_label = QLabel("Vol")
        volume_label.setObjectName("meta")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setFixedWidth(180)
        self.auto_btn = QPushButton()
        self.auto_btn.setObjectName("ghostBtn")
        controls_row.addWidget(volume_label)
        controls_row.addWidget(self.volume_slider)
        controls_row.addWidget(self.auto_btn)

        player_layout.addLayout(controls_row)
        outer.addWidget(player_bar)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        # Hidden state widgets used by action handlers and seed/playlists logic.
        self.shuffle_seed_input = QLineEdit(self)
        self.shuffle_seed_input.hide()
        self.saved_playlist_combo = QComboBox(self)
        self.saved_playlist_combo.hide()
        self.youtube_url = QLineEdit(self)
        self.youtube_url.hide()
        self.download_btn = QPushButton(self)
        self.download_btn.hide()

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("Space"), self, activated=self._toggle_play)
        QShortcut(QKeySequence("Ctrl+Right"), self, activated=self.play_next)
        QShortcut(QKeySequence("Ctrl+Left"), self, activated=self.play_prev)
        QShortcut(QKeySequence("Ctrl+Up"), self, activated=self._volume_up)
        QShortcut(QKeySequence("Ctrl+Down"), self, activated=self._volume_down)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self.open_settings)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.open_song_search)

    def _connect_events(self) -> None:
        self.settings_btn.clicked.connect(self.open_settings)
        self.import_btn.clicked.connect(self.open_import_modal)
        self.find_songs_btn.clicked.connect(self.open_song_search)
        self.library_btn.clicked.connect(self.open_library_modal)
        self.hero_play_btn.clicked.connect(self._on_hero_play)
        self.search_input.textChanged.connect(self._on_search)
        self.search_input.returnPressed.connect(self._play_first_search_result)
        self.playlist_table.itemDoubleClicked.connect(self._play_selected_item)
        self.saved_home_list.itemDoubleClicked.connect(self._open_saved_from_home)
        self.saved_view_all_btn.clicked.connect(self.open_library_modal)

        self.play_btn.clicked.connect(self._toggle_play)
        self.next_btn.clicked.connect(self.play_next)
        self.prev_btn.clicked.connect(self.play_prev)
        self.volume_slider.valueChanged.connect(self._on_volume_change)
        self.auto_btn.clicked.connect(self._toggle_auto_adjust)

        self.progress_slider.sliderPressed.connect(self._on_slider_pressed)
        self.progress_slider.sliderReleased.connect(self._on_slider_released)

    def _show_loading(self, message: str) -> None:
        if self.loading_dialog is None:
            self.loading_dialog = LoadingDialog(parent=self, modal=True)
        self.loading_dialog.set_message(message)
        self.loading_dialog.show()
        self.loading_dialog.raise_()
        QApplication.processEvents()

    def _update_loading(self, message: str) -> None:
        if self.loading_dialog and self.loading_dialog.isVisible():
            self.loading_dialog.set_message(message)
            QApplication.processEvents()

    def _hide_loading(self) -> None:
        if self.loading_dialog and self.loading_dialog.isVisible():
            self.loading_dialog.hide()
            QApplication.processEvents()

    def _on_background_status(self, message: str) -> None:
        self.status_bar.showMessage(message)
        self._update_loading(message)

    @staticmethod
    def _song_key(song: Path) -> str:
        try:
            return str(song.resolve())
        except Exception:
            return str(song)

    def _quick_metadata(self, song: Path) -> AudioMetadata:
        stem = song.stem.replace("_", " ").strip()
        artist = "Unknown Artist"
        title = stem or song.stem
        for sep in (" - ",):
            if sep in stem:
                left, right = stem.split(sep, 1)
                possible_artist = left.strip()
                possible_title = right.strip()
                if possible_artist and possible_title:
                    artist = possible_artist
                    title = possible_title
                break
        return AudioMetadata(
            title=title,
            artist=artist,
            album="Unknown Album",
            year="",
            genre="",
            duration_seconds=0.0,
            bitrate_kbps=0,
        )

    def _set_import_buttons_enabled(self, enabled: bool) -> None:
        self.import_btn.setEnabled(enabled)
        self.library_btn.setEnabled(enabled)

    def _start_local_import(self, worker: LocalImportThread, loading_message: str) -> None:
        if self.local_import_thread and self.local_import_thread.isRunning():
            self.status_bar.showMessage("Another import is already running")
            return
        self.local_import_thread = worker
        self._set_import_buttons_enabled(False)
        self._show_loading(loading_message)
        worker.status.connect(self._on_background_status)
        worker.finished_payload.connect(self._on_local_import_done)
        worker.failed.connect(self._on_local_import_failed)
        worker.finished.connect(self._on_local_import_finished)
        worker.start()

    def _on_local_import_done(self, payload: object) -> None:
        self._hide_loading()
        if not isinstance(payload, dict):
            QMessageBox.critical(self, "Import Failed", "Import returned an unexpected response.")
            return

        mode = str(payload.get("mode", ""))
        songs = [Path(p) for p in payload.get("songs", []) if isinstance(p, str)]
        if not songs:
            if mode == "zip":
                QMessageBox.information(
                    self,
                    "No Audio Found",
                    "ZIP extracted successfully, but no supported audio files were found.",
                )
            elif mode == "saved":
                playlist_name = str(payload.get("collection_name") or "Saved Playlist")
                QMessageBox.warning(
                    self,
                    "Playlist Empty",
                    f"Saved playlist '{playlist_name}' loaded, but none of its files currently exist on disk.",
                )
                self.status_bar.showMessage(f"Saved playlist '{playlist_name}' has no existing tracks")
            else:
                QMessageBox.information(self, "No Audio Found", "No supported audio files were found.")
            return

        shuffle_on_load = self.settings.get_bool("shuffle_on_load")
        seed = self.shuffle_seed_input.text().strip() or None
        used_seed = self.playlist_manager.set_playlist(songs, shuffle=shuffle_on_load, seed=seed)
        if used_seed:
            self.shuffle_seed_input.setText(used_seed)

        self.active_collection_name = str(payload.get("collection_name") or "Imported Playlist")
        self._metadata_cache.clear()
        self._art_cache.clear()
        self._refresh_playlist_view()

        if mode == "zip":
            target_dir = str(payload.get("target_dir", "-"))
            self.status_bar.showMessage(f"Imported {len(songs)} tracks from ZIP into {target_dir}")
        elif mode == "saved":
            playlist_name = str(payload.get("collection_name") or "Saved Playlist")
            self._refresh_saved_playlist_combo(select_name=playlist_name)
            self.status_bar.showMessage(f"Loaded saved playlist '{playlist_name}' with {len(songs)} tracks")
        else:
            recursive = bool(payload.get("recursive"))
            mode_text = "recursive" if recursive else "flat"
            message = f"Loaded {len(songs)} tracks ({mode_text} scan)"
            if used_seed:
                message += f" | seed: {used_seed}"
            self.status_bar.showMessage(message)

        if self.settings.get_bool("autoplay_on_load"):
            self.play_track(0)

    def _on_local_import_failed(self, message: str) -> None:
        self._hide_loading()
        QMessageBox.critical(self, "Import Failed", f"Could not complete import.\n\nDetails: {message}")
        self.status_bar.showMessage("Import failed")

    def _on_local_import_finished(self) -> None:
        self._set_import_buttons_enabled(True)
        self.local_import_thread = None

    def _cancel_metadata_thread(self, wait_ms: int = 0) -> None:
        thread = self.metadata_thread
        self.metadata_thread = None
        if thread is None:
            return

        if thread.isRunning():
            thread.requestInterruption()
            if wait_ms > 0:
                thread.wait(wait_ms)

        if not thread.isRunning():
            if thread in self._metadata_workers:
                self._metadata_workers.remove(thread)
            thread.deleteLater()

    def _start_metadata_prefetch(self, songs: List[Path]) -> None:
        pending: List[Path] = []
        seen: set[str] = set()
        for song in songs:
            key = self._song_key(song)
            if key in seen:
                continue
            seen.add(key)
            if key not in self._metadata_cache or key not in self._art_cache:
                pending.append(song)

        if not pending:
            return

        self._cancel_metadata_thread()
        self._metadata_generation += 1
        generation = self._metadata_generation

        thread = PlaylistMetadataThread(generation, pending, parent=self)
        self.metadata_thread = thread
        self._metadata_workers.append(thread)
        thread.song_ready.connect(self._on_metadata_song_ready)
        thread.batch_finished.connect(self._on_metadata_batch_finished)
        thread.failed.connect(self._on_metadata_batch_failed)
        thread.finished.connect(lambda thr=thread: self._on_metadata_worker_finished(thr))
        thread.start()

    def _on_metadata_worker_finished(self, thread: PlaylistMetadataThread) -> None:
        if thread in self._metadata_workers:
            self._metadata_workers.remove(thread)
        if self.metadata_thread is thread:
            self.metadata_thread = None
        thread.deleteLater()

    def _on_metadata_song_ready(
        self,
        generation: int,
        song_key: str,
        metadata_obj: object,
        art_bytes_obj: object,
    ) -> None:
        if generation != self._metadata_generation:
            return
        if not isinstance(metadata_obj, AudioMetadata):
            return

        metadata = metadata_obj
        self._metadata_cache[song_key] = metadata

        if isinstance(art_bytes_obj, (bytes, bytearray)) and art_bytes_obj:
            pixmap = QPixmap()
            if pixmap.loadFromData(bytes(art_bytes_obj)):
                self._art_cache[song_key] = pixmap
            else:
                self._art_cache.setdefault(song_key, None)
        else:
            self._art_cache.setdefault(song_key, None)

        item = self._playlist_row_lookup.get(song_key)
        if item is not None:
            song = Path(song_key)
            self._apply_metadata_to_item(item, song, metadata)
            item.setIcon(1, QIcon(self._art_pixmap_for_song(song, size=40, allow_blocking=False)))

        if not self.playlist_manager.playlist:
            return

        current_idx = self.playlist_manager.index
        if 0 <= current_idx < len(self.playlist_manager.playlist):
            current_song = self.playlist_manager.playlist[current_idx]
            is_active_track = self.player.playing or self.player.paused
            if is_active_track and self._song_key(current_song) == song_key:
                self.now_playing.setText(metadata.display_title())
                self.meta_label.setText(self._metadata_text(metadata, current_song))
                self.artwork_label.setPixmap(
                    self._art_pixmap_for_song(current_song, size=272, allow_blocking=False)
                )
                self._refresh_hero_banner()
                return

        first_song = self.playlist_manager.playlist[0]
        if self._song_key(first_song) == song_key:
            self._refresh_hero_banner()

    def _on_metadata_batch_finished(self, generation: int) -> None:
        if generation != self._metadata_generation:
            return
        self.metadata_thread = None

    def _on_metadata_batch_failed(self, generation: int, message: str) -> None:
        if generation != self._metadata_generation:
            return
        self.status_bar.showMessage(f"Metadata refresh failed: {message}")
        self.metadata_thread = None

    def _refresh_download_hint(self) -> None:
        mode = "default" if self.settings.get_bool("use_default_download_dir") else "prompt every download"
        spotify_ready = bool(
            self.settings.get_str("spotify_client_id") and self.settings.get_str("spotify_client_secret")
        )
        spotify_text = "Spotify import ready" if spotify_ready else "Spotify credentials missing"
        self.download_dir_hint.setText(
            f"Download dir: {self.settings.download_dir()} ({mode})  ·  {spotify_text}"
        )

    def _refresh_saved_playlist_combo(self, select_name: str | None = None) -> None:
        existing_selection = self.saved_playlist_combo.currentData()
        target_selection = select_name or (str(existing_selection) if existing_selection else None)

        names = self.playlist_manager.list_saved_playlists()
        self.saved_playlist_combo.blockSignals(True)
        self.saved_playlist_combo.clear()
        self.saved_playlist_combo.addItem("Saved playlists...", "")
        for name in names:
            self.saved_playlist_combo.addItem(name, name)

        idx = 0
        if target_selection:
            found = self.saved_playlist_combo.findData(target_selection)
            if found >= 0:
                idx = found
        self.saved_playlist_combo.setCurrentIndex(idx)
        self.saved_playlist_combo.blockSignals(False)
        self._refresh_saved_home_list(select_name=target_selection)

    def _selected_saved_playlist_name(self) -> str:
        value = self.saved_playlist_combo.currentData()
        if value is None:
            return ""
        return str(value).strip()

    def _refresh_saved_home_list(self, select_name: str | None = None) -> None:
        self.saved_home_list.clear()
        names = self.playlist_manager.list_saved_playlists()
        self.saved_count_label.setText(f"{len(names)} profiles")

        if not names:
            placeholder = QListWidgetItem("No saved playlists")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.saved_home_list.addItem(placeholder)
            return

        for name in names:
            count = len(self.playlist_manager.saved_playlists.get(name, []))
            item = QListWidgetItem(f"{name}\n{count} songs")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(f"Open saved playlist '{name}'")

            cover_song = None
            paths = self.playlist_manager.saved_playlists.get(name, [])
            if paths:
                probe = Path(paths[0])
                if probe.exists():
                    cover_song = probe
            icon_pixmap = (
                self._art_pixmap_for_song(cover_song, size=46, allow_blocking=False)
                if cover_song
                else self._placeholder_art_pixmap(name, size=46)
            )
            item.setIcon(QIcon(icon_pixmap))
            self.saved_home_list.addItem(item)
            if select_name and name == select_name:
                self.saved_home_list.setCurrentItem(item)

    def _open_saved_from_home(self, item: QListWidgetItem) -> None:
        name = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not name:
            return
        self.load_saved_playlist(name=name)

    def save_current_playlist(self, name: str | None = None) -> None:
        if not self.playlist_manager.playlist:
            QMessageBox.information(self, "No Playlist", "Load or import tracks before saving a playlist.")
            return

        if name is None:
            entered, ok = QInputDialog.getText(
                self,
                "Save Playlist",
                "Playlist name:",
                text=self._selected_saved_playlist_name(),
            )
            if not ok:
                return
            raw_name = entered
        else:
            raw_name = name

        normalized = " ".join(raw_name.strip().split())
        if not normalized:
            QMessageBox.information(self, "Missing Name", "Enter a playlist name.")
            return

        if self.playlist_manager.save_current_playlist(normalized):
            self._refresh_saved_playlist_combo(select_name=normalized)
            self.status_bar.showMessage(
                f"Saved playlist '{normalized}' ({len(self.playlist_manager.playlist)} tracks)"
            )

    def load_saved_playlist(self, name: str | None = None) -> None:
        target_name = " ".join((name or self._selected_saved_playlist_name()).strip().split())
        if target_name:
            self.saved_playlist_combo.setCurrentIndex(self.saved_playlist_combo.findData(target_name))
        name = target_name
        if not name:
            self.status_bar.showMessage("Select a saved playlist first")
            return
        if name not in self.playlist_manager.saved_playlists:
            QMessageBox.information(self, "Missing Playlist", f"Saved playlist '{name}' was not found.")
            return

        paths = self.playlist_manager.saved_playlists.get(name, [])
        self._refresh_saved_playlist_combo(select_name=name)
        self.status_bar.showMessage(f"Loading saved playlist '{name}'...")
        self._start_local_import(
            LocalImportThread.for_saved_playlist(name, paths, parent=self),
            f"Loading saved playlist '{name}'...",
        )

    def delete_saved_playlist(self, name: str | None = None) -> None:
        target_name = " ".join((name or self._selected_saved_playlist_name()).strip().split())
        if target_name:
            self.saved_playlist_combo.setCurrentIndex(self.saved_playlist_combo.findData(target_name))
        name = target_name
        if not name:
            self.status_bar.showMessage("Select a saved playlist to delete")
            return
        if name not in self.playlist_manager.saved_playlists:
            QMessageBox.information(self, "Missing Playlist", f"Saved playlist '{name}' was not found.")
            return

        answer = QMessageBox.question(
            self,
            "Delete Saved Playlist",
            f"Delete saved playlist '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        if self.playlist_manager.delete_saved_playlist(name):
            self._refresh_saved_playlist_combo()
            self.status_bar.showMessage(f"Deleted saved playlist '{name}'")

    def _on_saved_playlist_activated(self, _index: int) -> None:
        self.load_saved_playlist()

    def _refresh_playlist_view(self) -> None:
        self._metadata_generation += 1
        self._cancel_metadata_thread()
        self._playlist_row_lookup.clear()
        self.playlist_table.clear()
        pending_songs: List[Path] = []
        for row, song in enumerate(self.playlist_manager.filtered_playlist, start=1):
            try:
                added_text = datetime.fromtimestamp(song.stat().st_mtime).strftime("%b %d, %Y")
            except OSError:
                added_text = "-"
            item = QTreeWidgetItem(
                [
                    str(row),
                    "",
                    "",
                    "",
                    added_text,
                    "--:--",
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, str(song))
            metadata = self._metadata_for(song, allow_blocking=False)
            self._apply_metadata_to_item(item, song, metadata)
            art = self._art_pixmap_for_song(song, size=40, allow_blocking=False)
            item.setIcon(1, QIcon(art))
            self.playlist_table.addTopLevelItem(item)
            key = self._song_key(song)
            self._playlist_row_lookup[key] = item
            if key not in self._metadata_cache or key not in self._art_cache:
                pending_songs.append(song)

        shown = len(self.playlist_manager.filtered_playlist)
        total = len(self.playlist_manager.playlist)
        if self.playlist_manager.search_query:
            self.playlist_count_label.setText(f"{shown} shown of {total} tracks")
        else:
            self.playlist_count_label.setText(f"{total} tracks")
        if total == 0:
            self.artwork_label.setPixmap(self._placeholder_art_pixmap("S", size=272))

        self._refresh_hero_banner()
        self._highlight_current_song()
        self._update_hero_button()
        if pending_songs:
            self._start_metadata_prefetch(pending_songs)

    def _apply_metadata_to_item(self, item: QTreeWidgetItem, song: Path, metadata: AudioMetadata) -> None:
        duration = metadata.duration_seconds if metadata.duration_seconds > 0 else 0.0
        duration_text = self._fmt_seconds(duration) if duration > 0 else "--:--"
        item.setText(1, metadata.title)
        item.setText(2, metadata.artist)
        item.setText(3, metadata.album)
        item.setText(5, duration_text)

        meta_tooltip = (
            f"Artist: {metadata.artist}\n"
            f"Album: {metadata.album}\n"
            f"Year: {metadata.year or '-'}\n"
            f"Genre: {metadata.genre or '-'}\n"
            f"Bitrate: {metadata.bitrate_kbps if metadata.bitrate_kbps > 0 else '-'} kbps\n"
            f"Path: {song}"
        )
        item.setToolTip(1, meta_tooltip)

        if self.settings.get_bool("show_track_stats"):
            stats = self.playlist_manager.stats_for(song)
            item.setToolTip(
                0,
                (
                    f"Started: {stats.started}   "
                    f"Played: {stats.played}   "
                    f"Skipped: {stats.skipped}"
                ),
            )
        else:
            item.setToolTip(0, "")

    def _update_hero_button(self) -> None:
        if self.playlist_manager.playlist:
            self.hero_play_btn.setText("▶ Play")
            self.hero_play_btn.setToolTip("Play or pause current queue")
            return
        self.hero_play_btn.setText("Import & Play")
        self.hero_play_btn.setToolTip("Open import options to start playback")

    def _refresh_hero_banner(self) -> None:
        total = len(self.playlist_manager.playlist)
        if total == 0:
            self.hero_context.setText("Playlist")
            self.hero_title.setText("Your Queue")
            self.hero_subtitle.setText("Import or search songs to start")
            self.hero_art.setPixmap(self._placeholder_art_pixmap("S", size=118))
            return

        title = self.active_collection_name.strip() or "Your Queue"
        self.hero_context.setText("Collection")
        if self.playlist_manager.search_query:
            self.hero_context.setText("Search Results")
        self.hero_title.setText(title)
        self.hero_subtitle.setText(f"{total} songs")
        hero_song = self.playlist_manager.playlist[0]

        if self.player.playing and 0 <= self.playlist_manager.index < total:
            now_song = self.playlist_manager.playlist[self.playlist_manager.index]
            metadata = self._metadata_for(now_song, allow_blocking=False)
            self.hero_context.setText("Now Playing")
            self.hero_title.setText(metadata.title)
            artist = metadata.artist if metadata.artist else "Unknown Artist"
            self.hero_subtitle.setText(f"{artist}  ·  {total} songs in queue")
            hero_song = now_song
        self.hero_art.setPixmap(self._art_pixmap_for_song(hero_song, size=118, allow_blocking=False))

    def _on_hero_play(self) -> None:
        if not self.playlist_manager.playlist:
            self.open_import_modal()
            return
        self._toggle_play()

    def _metadata_for(self, song: Path, allow_blocking: bool = True) -> AudioMetadata:
        key = self._song_key(song)
        cached = self._metadata_cache.get(key)
        if cached is not None:
            return cached
        if not allow_blocking:
            return self._quick_metadata(song)
        loaded = read_audio_metadata(song)
        self._metadata_cache[key] = loaded
        return loaded

    def _placeholder_art_pixmap(self, token: str, size: int = 64) -> QPixmap:
        palette = [
            QColor("#253044"),
            QColor("#2b3a2d"),
            QColor("#3a2a3f"),
            QColor("#2d2239"),
            QColor("#3c2a2a"),
            QColor("#23333a"),
        ]
        idx = abs(hash(token)) % len(palette)
        bg = palette[idx]

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(bg)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, size, size, max(8, size * 0.16), max(8, size * 0.16))
        painter.setPen(QColor("#e8eef6"))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(max(9, int(size * 0.35)))
        painter.setFont(font)
        text = token.strip()[:1].upper() if token.strip() else "♪"
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
        return pixmap

    def _art_pixmap_for_song(
        self,
        song: Path | None,
        size: int = 64,
        allow_blocking: bool = True,
    ) -> QPixmap:
        if song is None:
            return self._placeholder_art_pixmap("music", size=size)

        key = self._song_key(song)
        base_pixmap = self._art_cache.get(key)
        if allow_blocking and base_pixmap is None and key not in self._art_cache:
            image_bytes = read_album_art_bytes(song)
            if image_bytes:
                probe = QPixmap()
                if probe.loadFromData(image_bytes):
                    base_pixmap = probe
            self._art_cache[key] = base_pixmap

        if base_pixmap and not base_pixmap.isNull():
            return base_pixmap.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )

        metadata = self._metadata_for(song, allow_blocking=allow_blocking)
        token = metadata.artist or metadata.title or song.stem
        return self._placeholder_art_pixmap(token, size=size)

    def _metadata_text(self, metadata: AudioMetadata, song: Path) -> str:
        year_text = metadata.year if metadata.year else "Unknown year"
        genre_text = metadata.genre if metadata.genre else "Unknown genre"
        duration = metadata.duration_seconds if metadata.duration_seconds > 0 else self.track_duration
        duration_text = self._fmt_seconds(duration)
        bitrate = f"{metadata.bitrate_kbps} kbps" if metadata.bitrate_kbps > 0 else "Unknown bitrate"
        return (
            f"Artist: {metadata.artist}   Album: {metadata.album}   Year: {year_text}\n"
            f"Genre: {genre_text}   Duration: {duration_text}   Bitrate: {bitrate}"
        )

    def open_import_modal(self) -> None:
        dialog = ImportDialog(self.settings.download_dir(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        source, value = dialog.payload()
        if not value:
            QMessageBox.information(self, "Missing Value", "Choose a source value before importing.")
            return

        if source == "folder":
            self._load_folder_path(Path(value))
            return
        if source == "zip":
            self._import_zip_path(Path(value))
            return
        if source == "spotify":
            self._import_spotify_playlist(value)
            return
        self._download_from_url(value)

    def open_library_modal(self) -> None:
        saved_counts = {
            name: len(paths) for name, paths in self.playlist_manager.saved_playlists.items()
        }
        dialog = LibraryDialog(saved_counts, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        action, value = dialog.payload()
        if action == "save":
            self.save_current_playlist(name=value)
            return
        if action == "load":
            self.load_saved_playlist(name=value)
            return
        if action == "delete":
            self.delete_saved_playlist(name=value)
            return
        self.shuffle_playlist(seed=value or None)

    def open_song_search(self) -> None:
        dialog = SongSearchDialog(initial_query=self.search_input.text().strip(), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        queries, replace_queue, save_name = dialog.payload()
        if not queries:
            return
        self._download_search_queries(queries, replace_queue=replace_queue, save_name=save_name)

    def _download_search_queries(self, queries: List[str], replace_queue: bool, save_name: str) -> None:
        folder = self._download_target_dir()
        if folder is None:
            return
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = folder / f"search-mix-{stamp}"
        target.mkdir(parents=True, exist_ok=True)

        self.find_songs_btn.setEnabled(False)
        self.status_bar.showMessage(f"Downloading {len(queries)} selected songs...")
        self._show_loading(f"Downloading {len(queries)} selected songs...")

        self.query_download_thread = QueryDownloadThread(queries, target, parent=self)
        self.query_download_thread.status.connect(self._on_background_status)
        self.query_download_thread.failed.connect(self._download_failed)
        self.query_download_thread.finished_files.connect(
            lambda files: self._search_download_done(files, replace_queue, save_name)
        )
        self.query_download_thread.finished.connect(lambda: self.find_songs_btn.setEnabled(True))
        self.query_download_thread.finished.connect(self._hide_loading)
        self.query_download_thread.start()

    def _search_download_done(self, files: List[str], replace_queue: bool, save_name: str) -> None:
        self._hide_loading()
        songs = [Path(p) for p in files]
        if not songs:
            self.status_bar.showMessage("No songs were downloaded from the search selection.")
            return

        if replace_queue or not self.playlist_manager.playlist:
            shuffle_on_load = self.settings.get_bool("shuffle_on_load")
            seed = self.shuffle_seed_input.text().strip() or None
            used_seed = self.playlist_manager.set_playlist(songs, shuffle=shuffle_on_load, seed=seed)
            if used_seed:
                self.shuffle_seed_input.setText(used_seed)
            self.active_collection_name = "Search Mix"
        else:
            merged = self.playlist_manager.playlist.copy()
            for song in songs:
                if song not in merged:
                    merged.append(song)
            self.playlist_manager.set_playlist(merged, shuffle=False)

        self._metadata_cache.clear()
        self._art_cache.clear()
        self._refresh_playlist_view()
        self.status_bar.showMessage(f"Added {len(songs)} songs from search")

        if save_name:
            self.save_current_playlist(name=save_name)
        if self.settings.get_bool("autoplay_on_load") and songs and not self.player.playing:
            self.play_track(0)

    def _prompt_spotify_import(self) -> None:
        url, ok = QInputDialog.getText(
            self,
            "Import Spotify Playlist",
            "Spotify playlist URL:",
        )
        if not ok:
            return
        self._import_spotify_playlist(url)

    def _import_spotify_playlist(self, playlist_url: str) -> None:
        clean_url = playlist_url.strip()
        if not clean_url:
            QMessageBox.information(self, "Missing URL", "Paste a Spotify playlist URL first.")
            return

        client_id = self.settings.get_str("spotify_client_id")
        client_secret = self.settings.get_str("spotify_client_secret")
        if not client_id or not client_secret:
            QMessageBox.warning(
                self,
                "Spotify Credentials Missing",
                "Set Spotify Client ID and Client Secret in Settings before importing Spotify playlists.",
            )
            return

        folder = self._download_target_dir()
        if folder is None:
            return
        folder.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = folder / f"spotify-import-{stamp}"
        target.mkdir(parents=True, exist_ok=True)

        self.import_btn.setEnabled(False)
        self.find_songs_btn.setEnabled(False)
        self.status_bar.showMessage("Starting Spotify playlist import...")
        self._show_loading("Starting Spotify playlist import...")

        self.spotify_thread = SpotifyImportThread(
            clean_url,
            target,
            client_id,
            client_secret,
            parent=self,
        )
        self.spotify_thread.status.connect(self._on_background_status)
        self.spotify_thread.failed.connect(self._download_failed)
        self.spotify_thread.finished_files.connect(self._spotify_import_done)
        self.spotify_thread.finished.connect(lambda: self.import_btn.setEnabled(True))
        self.spotify_thread.finished.connect(lambda: self.find_songs_btn.setEnabled(True))
        self.spotify_thread.finished.connect(self._hide_loading)
        self.spotify_thread.start()

    def _spotify_import_done(self, files: List[str], playlist_name: str) -> None:
        self._hide_loading()
        songs = [Path(p) for p in files]
        shuffle_on_load = self.settings.get_bool("shuffle_on_load")
        seed = self.shuffle_seed_input.text().strip() or None
        used_seed = self.playlist_manager.set_playlist(songs, shuffle=shuffle_on_load, seed=seed)
        if used_seed:
            self.shuffle_seed_input.setText(used_seed)

        self.active_collection_name = playlist_name
        self._metadata_cache.clear()
        self._art_cache.clear()
        self._refresh_playlist_view()
        self.status_bar.showMessage(f"Imported Spotify playlist '{playlist_name}' with {len(songs)} tracks")

        if songs and self.settings.get_bool("autoplay_on_load"):
            self.play_track(0)

    def _load_folder_path(self, folder_path: Path) -> None:
        if not folder_path.exists() or not folder_path.is_dir():
            QMessageBox.warning(self, "Invalid Folder", f"Not a valid folder:\n{folder_path}")
            return

        recursive = self.settings.get_bool("recursive_scan")
        self.status_bar.showMessage("Scanning folder and building playlist...")
        self._start_local_import(
            LocalImportThread.for_folder(folder_path, recursive=recursive, parent=self),
            "Scanning folder and building playlist...",
        )

    def _import_zip_path(self, zip_path: Path) -> None:
        if not zip_path.exists() or not zip_path.is_file():
            QMessageBox.warning(self, "Invalid ZIP", f"Not a valid ZIP file:\n{zip_path}")
            return

        self.status_bar.showMessage("Importing ZIP and indexing tracks...")
        self._start_local_import(
            LocalImportThread.for_zip(zip_path, imports_dir=self.settings.imports_dir(), parent=self),
            "Importing ZIP and indexing tracks...",
        )

    def _download_from_url(self, url: str) -> None:
        clean_url = url.strip()
        if not clean_url:
            QMessageBox.information(self, "Missing URL", "Paste a YouTube playlist URL first.")
            return

        self.youtube_url.setText(clean_url)
        self.download_playlist(url=clean_url)

    def load_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose audio folder")
        if not folder:
            return
        self._load_folder_path(Path(folder))

    def import_zip_archive(self) -> None:
        zip_path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Import ZIP archive",
            "",
            "ZIP Archives (*.zip)",
        )
        if not zip_path_str:
            return
        self._import_zip_path(Path(zip_path_str))

    def shuffle_playlist(self, seed: str | None = None) -> None:
        if not self.playlist_manager.playlist:
            self.status_bar.showMessage("Load a folder, ZIP, or playlist before shuffling")
            return

        if seed is None:
            seed = self.shuffle_seed_input.text().strip() or None
        used_seed = self.playlist_manager.reshuffle(seed=seed)
        if not used_seed:
            return

        self.shuffle_seed_input.setText(used_seed)
        self._refresh_playlist_view()
        self.status_bar.showMessage(f"Shuffled with seed: {used_seed}")

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

    def _play_selected_item(self, item: QTreeWidgetItem, _column: int) -> None:
        path_str = item.data(0, Qt.ItemDataRole.UserRole)
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

        metadata = self._metadata_for(song, allow_blocking=False)
        self.now_playing.setText(metadata.display_title())
        self.meta_label.setText(self._metadata_text(metadata, song))
        self.path_label.setText(str(song.parent))
        self.artwork_label.setPixmap(self._art_pixmap_for_song(song, size=272, allow_blocking=False))

        display_duration = metadata.duration_seconds if metadata.duration_seconds > 0 else self.track_duration
        self.time_total.setText(self._fmt_seconds(display_duration))
        self.play_btn.setText("Pause")
        self.status_bar.showMessage(f"Now playing: {song.name}")

        self._refresh_playlist_view()

    def _highlight_current_song(self) -> None:
        if not self.playlist_manager.playlist:
            return
        song = self.playlist_manager.playlist[self.playlist_manager.index]
        for i in range(self.playlist_table.topLevelItemCount()):
            item = self.playlist_table.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == str(song):
                self.playlist_table.setCurrentItem(item)
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
        self.volume_slider.setValue(min(100, self.volume_slider.value() + 2))

    def _volume_down(self) -> None:
        self.volume_slider.setValue(max(0, self.volume_slider.value() - 2))

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
            change = 0.01 if random.choice((True, False)) else -0.02
            current_volume = self.volume_slider.value() / 100.0
            new_volume = max(0.0, min(1.0, current_volume + change))
            self.volume_slider.setValue(int(new_volume * 100))
            self.status_bar.showMessage(f"Dynamic volume adjusted to {int(new_volume * 100)}%")
            self.next_adjust_at = time.time() + random.randint(6 * 60, 24 * 60)

    def _toggle_auto_adjust(self) -> None:
        self.auto_adjust_enabled = not self.auto_adjust_enabled
        self.settings.update({"auto_adjust_enabled": self.auto_adjust_enabled})
        self._update_auto_button()

        if self.auto_adjust_enabled:
            self.next_adjust_at = time.time() + random.randint(6 * 60, 24 * 60)
            self.status_bar.showMessage("Dynamic volume enabled")
        else:
            self.status_bar.showMessage("Dynamic volume disabled")

    def _update_auto_button(self) -> None:
        self.auto_btn.setText("Dynamic Volume: On" if self.auto_adjust_enabled else "Dynamic Volume: Off")

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        values = dialog.values()
        self.settings.update(values)

        self.theme_name = self.settings.get_str("theme")
        if self.theme_name not in THEME_OPTIONS.values():
            self.theme_name = "pitch_black"

        self.auto_adjust_enabled = self.settings.get_bool("auto_adjust_enabled")
        self._update_auto_button()
        if self.auto_adjust_enabled:
            self.next_adjust_at = time.time() + random.randint(6 * 60, 24 * 60)

        self.volume_slider.setValue(self.settings.get_int("default_volume"))
        self._apply_theme()
        self._refresh_download_hint()
        self._refresh_playlist_view()
        self.status_bar.showMessage("Settings saved")

    def refresh_metadata_cache(self) -> None:
        self._metadata_cache.clear()
        self._art_cache.clear()
        self._refresh_playlist_view()
        self.status_bar.showMessage("Metadata cache cleared")

    def open_debug_panel(self) -> None:
        dialog = DebugDialog(self._debug_snapshot, self)
        dialog.exec()

    def _debug_snapshot(self) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        queue_count = len(self.playlist_manager.playlist)
        filtered_count = len(self.playlist_manager.filtered_playlist)
        index = self.playlist_manager.index
        try:
            current_seconds = self.player.current_seconds()
        except Exception:
            current_seconds = 0.0
        current_song = "-"
        if queue_count > 0 and 0 <= index < queue_count:
            current_song = str(self.playlist_manager.playlist[index])

        lines: List[str] = [
            "Sabrinth Player Debug Snapshot",
            f"Generated: {now}",
            "",
            "[App]",
            f"Window title: {self.windowTitle()}",
            f"Theme: {self.theme_name}",
            f"App dir: {self.settings.app_dir}",
            f"Settings path: {self.settings.path}",
            "",
            "[Playback]",
            f"Queue tracks: {queue_count}",
            f"Filtered tracks: {filtered_count}",
            f"Current index: {index}",
            f"Current song: {current_song}",
            f"Player playing: {self.player.playing}",
            f"Player paused: {self.player.paused}",
            f"Current seconds: {self._fmt_seconds(current_seconds)}",
            f"Track duration: {self._fmt_seconds(self.track_duration)}",
            f"Volume slider: {self.volume_slider.value()}%",
            f"Dynamic volume: {'on' if self.auto_adjust_enabled else 'off'}",
            "",
            "[Library]",
            f"Saved profiles: {len(self.playlist_manager.saved_playlists)}",
            f"Active collection: {self.active_collection_name}",
            f"Shuffle seed: {self.playlist_manager.shuffle_seed or '-'}",
            f"Search query: {self.playlist_manager.search_query or '-'}",
            "",
            "[Imports]",
            f"Use default download dir: {self.settings.get_bool('use_default_download_dir')}",
            f"Download dir: {self.settings.download_dir()}",
            f"Imports dir: {self.settings.imports_dir()}",
            f"Spotify credentials set: {bool(self.settings.get_str('spotify_client_id') and self.settings.get_str('spotify_client_secret'))}",
            f"Download thread active: {bool(self.download_thread and self.download_thread.isRunning())}",
            f"Search download active: {bool(self.query_download_thread and self.query_download_thread.isRunning())}",
            f"Spotify import active: {bool(self.spotify_thread and self.spotify_thread.isRunning())}",
            f"Local import active: {bool(self.local_import_thread and self.local_import_thread.isRunning())}",
            "",
            "[Metadata]",
            f"Metadata worker active: {bool(self.metadata_thread and self.metadata_thread.isRunning())}",
            f"Cached tracks: {len(self._metadata_cache)}",
        ]

        if self.playlist_manager.saved_playlists:
            lines.append("")
            lines.append("[Saved Profiles Detail]")
            for name in sorted(self.playlist_manager.saved_playlists.keys(), key=str.lower):
                count = len(self.playlist_manager.saved_playlists.get(name, []))
                lines.append(f"- {name}: {count} tracks")

        return "\n".join(lines)

    def _download_target_dir(self) -> Path | None:
        if self.settings.get_bool("use_default_download_dir"):
            return self.settings.download_dir()

        chosen = QFileDialog.getExistingDirectory(self, "Choose download folder")
        if not chosen:
            return None
        return Path(chosen)

    def download_playlist(self, url: str | None = None) -> None:
        url = (url or self.youtube_url.text()).strip()
        if not url:
            QMessageBox.information(self, "Missing URL", "Paste a YouTube playlist URL first.")
            return

        folder = self._download_target_dir()
        if folder is None:
            return

        folder.mkdir(parents=True, exist_ok=True)
        self.download_btn.setEnabled(False)
        self.status_bar.showMessage(f"Downloading playlist to {folder}...")
        self._show_loading(f"Downloading playlist to {folder}...")

        self.download_thread = DownloadThread(url, folder, parent=self)
        self.download_thread.status.connect(self._on_background_status)
        self.download_thread.failed.connect(self._download_failed)
        self.download_thread.finished_files.connect(self._download_done)
        self.download_thread.finished.connect(lambda: self.download_btn.setEnabled(True))
        self.download_thread.finished.connect(self._hide_loading)
        self.download_thread.start()

    def _download_done(self, files: List[str]) -> None:
        self._hide_loading()
        songs = [Path(p) for p in files]

        shuffle_on_load = self.settings.get_bool("shuffle_on_load")
        seed = self.shuffle_seed_input.text().strip() or None
        used_seed = self.playlist_manager.set_playlist(songs, shuffle=shuffle_on_load, seed=seed)
        if used_seed:
            self.shuffle_seed_input.setText(used_seed)

        self.active_collection_name = "YouTube Playlist"
        self._metadata_cache.clear()
        self._art_cache.clear()
        self._refresh_playlist_view()
        self.status_bar.showMessage(f"Playlist ready with {len(songs)} tracks")
        if songs and self.settings.get_bool("autoplay_on_load"):
            self.play_track(0)

    def _download_failed(self, message: str) -> None:
        self._hide_loading()
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

    def _animate_logo_glow(self) -> None:
        self._logo_phase += 0.25
        radius = 10 + (math.sin(self._logo_phase) + 1.0) * 8
        alpha = int(80 + (math.sin(self._logo_phase * 0.8) + 1.0) * 55)
        self.logo_glow.setBlurRadius(radius)
        self.logo_glow.setColor(QColor(255, 255, 255, max(40, min(220, alpha))))

    def _apply_theme(self) -> None:
        self.theme_name = "pitch_black"
        self.setStyleSheet(
            """
            QMainWindow { background: #020202; }
            #appRoot {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #070708,
                    stop:0.34 #110910,
                    stop:0.62 #12080d,
                    stop:1 #050506
                );
            }
            QMenuBar {
                background: #060607;
                color: #f4f6f8;
                border-bottom: 1px solid #18191c;
                padding: 3px;
            }
            QMenuBar::item {
                background: transparent;
                padding: 5px 10px;
                border-radius: 8px;
                margin: 2px;
            }
            QMenuBar::item:selected { background: #16171a; }
            QMenu {
                background: #0b0b0d;
                color: #edf1f5;
                border: 1px solid #24262a;
            }
            QMenu::item:selected { background: #1b1d23; }

            #header {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #070708, stop:0.45 #120a14, stop:1 #1a0b13);
                border-bottom: 1px solid #232428;
            }
            #body {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0b0b0d, stop:0.36 #130d14, stop:1 #0a0a0b);
            }
            #searchContainer {
                background: #0e1014;
                border: 1px solid #2a2f38;
                border-radius: 14px;
            }
            #searchContainer QLineEdit {
                background: transparent;
                border: none;
                padding: 6px 8px;
            }
            #searchContainer QLineEdit:focus { border: none; }
            #navRail {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0d0f14, stop:1 #0a0a0d);
                border: 1px solid #252a31;
                border-radius: 16px;
            }
            #centerPane { background: transparent; border: none; }
            #heroCard {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #142016,
                    stop:0.38 #202735,
                    stop:1 #151a22
                );
                border: 1px solid #2a3442;
                border-radius: 18px;
            }
            #heroArt {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #26cf68, stop:1 #1a3a2a);
                color: #ffffff;
                border-radius: 14px;
                font-size: 44px;
                font-weight: 800;
            }
            #heroContext { color: #cfd8e2; font-size: 12px; }
            #heroTitle { color: #ffffff; font-size: 38px; font-weight: 800; letter-spacing: 0.2px; }
            #heroSubtitle { color: #b6c2ce; font-size: 13px; }
            #title { color: #f8fafc; font-size: 28px; font-weight: 700; letter-spacing: 0.3px; }
            #subtitle { color: #9ca7b1; font-size: 12px; }
            #sectionTitle {
                color: #b6c0ca;
                font-size: 12px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 1.1px;
            }
            #leftPanel, #rightPanel, #playlistPanel, #artCard, #savedPanel {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0d0e11, stop:1 #0a0a0c);
                border: 1px solid #2a2d33;
                border-radius: 18px;
            }
            #playerBar {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0a0a0d, stop:0.5 #130b13, stop:1 #13070d);
                border-top: 1px solid #262a31;
            }

            QLineEdit {
                background: #0f1014;
                color: #f2f4f8;
                border: 1px solid #2d3139;
                border-radius: 10px;
                padding: 10px;
            }
            QLineEdit:focus { border: 1px solid #2de774; }
            QComboBox {
                background: #101115;
                color: #f0f4f8;
                border: 1px solid #2d3139;
                border-radius: 10px;
                padding: 9px 10px;
            }
            QComboBox:focus { border: 1px solid #2de774; }
            QComboBox::drop-down { border: none; width: 22px; }
            QComboBox QAbstractItemView {
                background: #0d0e11;
                color: #eef2f6;
                border: 1px solid #2a2e35;
                selection-background-color: #1f3b2d;
            }

            QTreeWidget#playlistTable {
                background: #0f1014;
                color: #e5eaf0;
                border: 1px solid #2d3139;
                border-radius: 12px;
                outline: none;
                alternate-background-color: #10131a;
            }
            QTreeWidget#playlistTable::item {
                padding: 8px 6px;
                border-radius: 8px;
            }
            QTreeWidget#playlistTable::item:selected { background: #1f3b2d; color: #ffffff; }
            QTreeWidget#playlistTable::item:hover { background: #17212c; }
            QListWidget#savedHomeList {
                background: transparent;
                border: none;
                color: #e1e8ef;
                outline: none;
            }
            QListWidget#savedHomeList::item {
                border: 1px solid #2f3640;
                border-radius: 12px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #141921, stop:1 #10141b);
                margin: 2px;
                padding: 10px;
            }
            QListWidget#savedHomeList::item:selected {
                border: 1px solid #2de774;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1f3428, stop:1 #16221c);
                color: #ffffff;
            }
            QHeaderView::section {
                background: #141922;
                color: #9aa8b7;
                border: none;
                border-bottom: 1px solid #2c3440;
                padding: 8px 10px;
                font-size: 11px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.7px;
            }

            QPushButton {
                color: #e7ebef;
                border-radius: 10px;
                padding: 8px 14px;
                border: 1px solid #333842;
                background: #16181e;
            }
            QPushButton#primaryBtn {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #25c965,
                    stop:1 #1ca354
                );
                border: 1px solid #2de774;
                color: #ffffff;
                font-weight: 600;
            }
            QPushButton#controlBtn {
                background: #101217;
                border: 1px solid #2f343d;
                font-weight: 600;
                min-height: 32px;
            }
            QPushButton#heroPlayBtn {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #28d96c,
                    stop:1 #1eab57
                );
                border: 1px solid #2de674;
                color: #ffffff;
                font-weight: 700;
                border-radius: 16px;
                padding: 8px 18px;
            }
            QPushButton#ghostBtn {
                background: transparent;
                border: 1px solid #3a404a;
                color: #e8edf3;
            }
            QPushButton#chipBtn {
                background: #13161b;
                border: 1px solid #313742;
                border-radius: 12px;
                padding: 6px 14px;
            }
            QPushButton#chipBtn:checked {
                background: #1f3528;
                border: 1px solid #2de774;
            }
            QPushButton#railBtn {
                background: #12151a;
                border: 1px solid #313743;
                border-radius: 10px;
                font-size: 16px;
            }
            QPushButton#railBtn:checked {
                background: #1c3125;
                border: 1px solid #2de774;
            }
            QPushButton:hover { border-color: #2de774; }

            QLabel#nowPlaying { color: #ffffff; font-size: 27px; font-weight: 700; }
            QLabel#meta { color: #a9b4bf; font-size: 13px; }
            QLabel#path { color: #818d99; font-size: 12px; }
            QLabel#time { color: #b6c0ca; }
            QLabel#artworkLarge {
                border: 1px solid #2f3641;
                border-radius: 16px;
                background: #11161d;
            }

            QSlider::groove:horizontal { background: #242933; height: 6px; border-radius: 3px; }
            QSlider::handle:horizontal {
                background: #2cd96e;
                border: 1px solid #30eb78;
                width: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }

            QStatusBar { background: #08090b; color: #b7c1cc; border-top: 1px solid #20242b; }
            QScrollBar:vertical {
                background: transparent;
                width: 12px;
                margin: 8px 2px 8px 2px;
            }
            QScrollBar::handle:vertical {
                background: #353b44;
                min-height: 30px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical:hover { background: #4a5260; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            """
        )

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.settings.update(
            {
                "theme": self.theme_name,
                "default_volume": self.volume_slider.value(),
                "auto_adjust_enabled": self.auto_adjust_enabled,
            }
        )

        self.player.shutdown()
        if self.loading_dialog and self.loading_dialog.isVisible():
            self.loading_dialog.hide()
        if self.local_import_thread and self.local_import_thread.isRunning():
            self.local_import_thread.requestInterruption()
            self.local_import_thread.quit()
            self.local_import_thread.wait(1000)
        self._cancel_metadata_thread(wait_ms=1000)
        for worker in list(self._metadata_workers):
            if worker.isRunning():
                worker.requestInterruption()
                worker.wait(1000)
            if worker in self._metadata_workers:
                self._metadata_workers.remove(worker)
            worker.deleteLater()
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.quit()
            self.download_thread.wait(1000)
        if self.query_download_thread and self.query_download_thread.isRunning():
            self.query_download_thread.quit()
            self.query_download_thread.wait(1000)
        if self.spotify_thread and self.spotify_thread.isRunning():
            self.spotify_thread.quit()
            self.spotify_thread.wait(1000)
        super().closeEvent(event)
