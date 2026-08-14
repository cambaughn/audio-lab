"""Application bootstrap. The main window arrives at CP4."""

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from audio_lab.ui import theme
    from audio_lab.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Audio Lab")
    app.setStyleSheet(theme.stylesheet())
    window = MainWindow()
    window.show()
    return app.exec()
