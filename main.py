import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ui import LoadingDialog, MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Sabrinth Player")
    app.setOrganizationName("Sabrinth")
    signal.signal(signal.SIGINT, lambda *_args: app.quit())
    signal_pump = QTimer()
    signal_pump.setInterval(250)
    signal_pump.timeout.connect(lambda: None)
    signal_pump.start()

    startup = LoadingDialog("Launching Sabrinth Player...", modal=False)
    startup.show()
    app.processEvents()
    startup.set_message("Loading interface and audio engine...")
    app.processEvents()

    window = MainWindow()
    startup.set_message("Finalizing startup...")
    app.processEvents()
    window.show()
    startup.close()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
