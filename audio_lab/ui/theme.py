"""Centralized visual tokens — vintage industrial IMAX-console direction.

Single source of truth for the approved look (see docs/ui-style.md):
black background, monochrome amber foreground, thin outlined controls,
square corners, compact industrial typography. Adjust appearance here,
never in individual widgets. Ported verbatim from Identity Lab v0.1.0.
"""

# Colors
BG = "#0b0a07"           # near-black, slightly warm
BG_PANEL = "#0f0d09"     # panel background, barely lifted from BG
AMBER = "#ffb000"        # primary text, borders, values
AMBER_DIM = "#9c7420"    # secondary text, inactive labels, separators
AMBER_FAINT = "#4a3a14"  # subtle borders, disabled outlines
ERROR = "#ff4f30"        # restrained console red-orange for warnings/errors

# Geometry
BORDER_W = 1             # px, thin outlines everywhere
RADIUS = 2               # px, mostly-square corners
SPACING = 8              # px, base layout spacing
PAD = 6                  # px, control padding

# Typography — system/redistributable monospace stack, no proprietary fonts
FONT_STACK = '"Menlo", "SF Mono", "Monaco", "Courier New", monospace'
FONT_SIZE = 12           # px, base
FONT_SIZE_SMALL = 10     # px, footnotes / consent notice
FONT_SIZE_STATE = 18     # px, big state text in the preview area

# Glow — reserved token; kept at 0 (off) until it can be added without
# hurting readability. Restraint is part of the approved direction.
GLOW_INTENSITY = 0


def stylesheet() -> str:
    """Application-wide QSS built from the tokens above."""
    return f"""
    QWidget {{
        background-color: {BG};
        color: {AMBER};
        font-family: {FONT_STACK};
        font-size: {FONT_SIZE}px;
    }}
    QMainWindow, QDialog {{
        background-color: {BG};
    }}
    QGroupBox {{
        background-color: {BG_PANEL};
        border: {BORDER_W}px solid {AMBER_DIM};
        border-radius: {RADIUS}px;
        margin-top: {SPACING + 2}px;
        padding: {PAD + 2}px {PAD}px {PAD}px {PAD}px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: {PAD}px;
        padding: 0 {PAD - 2}px;
        color: {AMBER_DIM};
        background-color: {BG};
    }}
    QPushButton {{
        background-color: {BG_PANEL};
        border: {BORDER_W}px solid {AMBER};
        border-radius: {RADIUS}px;
        color: {AMBER};
        padding: {PAD}px {PAD + 4}px;
    }}
    QPushButton:hover {{
        background-color: #1a1608;
    }}
    QPushButton:pressed {{
        background-color: {AMBER};
        color: {BG};
    }}
    QPushButton:disabled {{
        border-color: {AMBER_FAINT};
        color: {AMBER_FAINT};
    }}
    QPushButton#recording, QPushButton#recording:pressed, QPushButton#recording:hover {{
        background-color: {AMBER};
        color: {BG};
        border-color: {AMBER};
        font-weight: bold;
    }}
    QPushButton#danger {{
        border-color: {ERROR};
        color: {ERROR};
    }}
    QPushButton#danger:pressed {{
        background-color: {ERROR};
        color: {BG};
    }}
    QListWidget {{
        background-color: {BG};
        border: {BORDER_W}px solid {AMBER_DIM};
        border-radius: {RADIUS}px;
        color: {AMBER};
        outline: none;
    }}
    QListWidget::item {{
        padding: {PAD}px;
        border-bottom: {BORDER_W}px solid {AMBER_FAINT};
    }}
    QListWidget::item:selected {{
        background-color: #1a1608;
        color: {AMBER};
        border-left: 2px solid {AMBER};
    }}
    QComboBox {{
        background-color: {BG_PANEL};
        border: {BORDER_W}px solid {AMBER_DIM};
        border-radius: {RADIUS}px;
        color: {AMBER};
        padding: {PAD - 2}px {PAD}px;
        combobox-popup: 0;  /* non-native dropdown: aligns under the control */
    }}
    QComboBox::drop-down {{
        border: none;
        width: 18px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {AMBER};
        margin-right: 6px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {BG_PANEL};
        border: {BORDER_W}px solid {AMBER_DIM};
        color: {AMBER};
        selection-background-color: {AMBER};
        selection-color: {BG};
        outline: none;
    }}
    QComboBox QAbstractItemView::item {{
        min-height: 20px;
        padding: 2px {PAD}px;
    }}
    QLabel {{
        background: transparent;
    }}
    QLabel#secondary {{
        color: {AMBER_DIM};
    }}
    QLabel#consent {{
        color: {AMBER_DIM};
        font-size: {FONT_SIZE_SMALL}px;
        border-top: {BORDER_W}px solid {AMBER_FAINT};
        padding-top: {PAD - 2}px;
    }}
    QLabel#error {{
        color: {ERROR};
    }}
    QScrollArea {{
        border: none;
        background-color: {BG};
    }}
    QScrollBar:vertical {{
        background: {BG};
        width: 8px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {AMBER_FAINT};
        border-radius: {RADIUS}px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {AMBER_DIM};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QToolTip {{
        background-color: {BG_PANEL};
        color: {AMBER};
        border: {BORDER_W}px solid {AMBER_DIM};
    }}
    QCheckBox {{
        color: {AMBER};
        spacing: {PAD}px;
    }}
    QCheckBox::indicator {{
        width: 12px;
        height: 12px;
        border: {BORDER_W}px solid {AMBER};
        border-radius: {RADIUS}px;
        background-color: {BG_PANEL};
    }}
    QCheckBox::indicator:checked {{
        background-color: {AMBER};
    }}
    QCheckBox::indicator:disabled {{
        border-color: {AMBER_FAINT};
    }}
    QSlider::groove:horizontal {{
        height: 2px;
        background: {AMBER_DIM};
    }}
    QSlider::handle:horizontal {{
        width: 10px;
        height: 14px;
        margin: -7px 0;
        background: {AMBER};
        border-radius: {RADIUS}px;
    }}
    QLineEdit {{
        background-color: {BG_PANEL};
        border: {BORDER_W}px solid {AMBER_DIM};
        border-radius: {RADIUS}px;
        color: {AMBER};
        padding: {PAD - 2}px {PAD}px;
        selection-background-color: {AMBER};
        selection-color: {BG};
    }}
    QLineEdit:focus {{
        border-color: {AMBER};
    }}
    QPlainTextEdit {{
        background-color: {BG};
        color: {AMBER_DIM};
        border: {BORDER_W}px solid {AMBER_FAINT};
        border-radius: {RADIUS}px;
        font-size: {FONT_SIZE_SMALL}px;
    }}
    """
