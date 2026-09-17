"""Attributed conversation view — monospace turn list.

Batch 3 scope: attributed transcripts only. Assistant turns and
ephemeral/persistence tags join in Batch 4.
"""

from PySide6.QtWidgets import QPlainTextEdit

from audio_lab.ui import theme


def format_turn(label: str, similarity: float | None, text: str) -> str:
    """Pure formatting — '[CAMERON 0.63] transcript' / '[UNKNOWN] transcript'."""
    sim = f" {similarity:.2f}" if similarity is not None else ""
    return f"[{label}{sim}] {text}"


class ConversationView(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(500)
        self.setPlaceholderText("PUSH-TO-TALK TURNS APPEAR HERE")
        # conversation reads as primary content: base font size, amber
        self.setStyleSheet(
            f"QPlainTextEdit {{ color: {theme.AMBER}; "
            f"font-size: {theme.FONT_SIZE}px; }}"
        )

    def add_turn(self, label: str, similarity: float | None, text: str) -> None:
        self.appendPlainText(format_turn(label, similarity, text))
