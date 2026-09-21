"""Shared fixtures. A QApplication on the offscreen platform backs both
Qt signal machinery and the widget tests; none of these tests require a
microphone, models, a network, or a display."""

import os

import pytest

# must be set before the first QApplication is constructed
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def qt_core_app():
    app = QApplication.instance() or QApplication([])
    yield app
