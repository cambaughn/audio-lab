"""Persisted user settings — JSON in the macOS app-data directory.

Settings live at ~/Library/Application Support/AudioLab/settings.json.
Loading is tolerant: a missing, corrupted, or wrongly-typed file falls back
to defaults (per-field where possible) instead of crashing the app.
Pattern inherited from Identity Lab v0.1.0.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

APP_DATA_DIR = Path.home() / "Library" / "Application Support" / "AudioLab"
SETTINGS_FILENAME = "settings.json"

THRESHOLD_RANGE = (0.05, 0.95)
MARGIN_RANGE = (0.0, 0.5)
TOP_K_RANGE = (1, 10)


@dataclass
class AppSettings:
    input_device_name: str | None = None   # real system device name
    debug_mode: bool = False
    recognition_threshold: float = 0.40    # conversational recognition
    private_access_threshold: float = 0.55 # stricter: loads private context
    match_margin: float = 0.10             # best must beat 2nd-best by this
    top_k: int = 3                         # enrollment samples averaged per score
    use_fake_llm: bool = True              # real adapter arrives at CP11
    window_geometry: str | None = None     # base64-encoded Qt geometry blob


def settings_path(data_dir: Path | None = None) -> Path:
    return (data_dir or APP_DATA_DIR) / SETTINGS_FILENAME


def _valid_int(value, lo: int, hi: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi


def _valid_float(value, lo: float, hi: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and lo <= float(value) <= hi
    )


def load_settings(path: Path | None = None) -> AppSettings:
    """Load settings, falling back to defaults on any malformed input."""
    path = path or settings_path()
    defaults = AppSettings()
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return defaults
    if not isinstance(raw, dict):
        return defaults

    loaded = AppSettings()
    v = raw.get("input_device_name")
    if isinstance(v, str) or v is None:
        loaded.input_device_name = v
    v = raw.get("debug_mode")
    if isinstance(v, bool):
        loaded.debug_mode = v
    v = raw.get("recognition_threshold")
    if _valid_float(v, *THRESHOLD_RANGE):
        loaded.recognition_threshold = float(v)
    v = raw.get("private_access_threshold")
    if _valid_float(v, *THRESHOLD_RANGE):
        loaded.private_access_threshold = float(v)
    v = raw.get("match_margin")
    if _valid_float(v, *MARGIN_RANGE):
        loaded.match_margin = float(v)
    v = raw.get("top_k")
    if _valid_int(v, *TOP_K_RANGE):
        loaded.top_k = v
    v = raw.get("use_fake_llm")
    if isinstance(v, bool):
        loaded.use_fake_llm = v
    v = raw.get("window_geometry")
    if isinstance(v, str) or v is None:
        loaded.window_geometry = v
    return loaded


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    """Atomically write settings as JSON, creating the directory if needed."""
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=2))
    tmp.replace(path)
