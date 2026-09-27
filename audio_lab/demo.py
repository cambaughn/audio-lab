"""Developer-only demo mode — populate the REAL UI for a screenshot.

This is NOT a product feature and it does not alter the experiment. Launch:

    python -m audio_lab --demo-screenshot

It renders the real widgets via MainWindow(demo_mode=True), which starts
NONE of the real subsystems: no microphone, no speaker/STT models, no
Anthropic or network call, and no access to the speaker or conversation
databases. Nothing is persisted.

All content below is fixed and fictional. The score and latency values are
representative of the measurements recorded in docs/, not measured during
this run. The guest LLM request is produced by the real ContextRouter, so
the private fact ("54719") is genuinely absent from it — the same guarantee
the privacy tests assert, shown in the UI.
"""

import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from audio_lab.audio.devices import InputDevice
from audio_lab.conversation.ephemeral import EphemeralRegistry
from audio_lab.conversation.router import ContextRouter, build_request
from audio_lab.identity.decision import AccessTier, RecognitionDecision
from audio_lab.ui import theme
from audio_lab.ui.main_window import MainWindow

GUEST_QUESTION = "What's Cameron's spaceship code?"

# (label, similarity, text, tag) — rendered exactly as the real UI renders a
# real run: verified turns carry no scope tag, guest turns are tagged.
CONVERSATION = [
    ("CAMERON", 0.66, "Remember my spaceship code is 54719.", None),
    ("ASSISTANT", None, "Noted — saved to your private memory.", None),
    ("CAMERON", 0.62, "What's my spaceship code?", None),
    ("ASSISTANT", None, "Your spaceship code is 54719.", None),
    ("UNKNOWN", 0.12, GUEST_QUESTION, "EPHEMERAL — NOT PERSISTED"),
    ("ASSISTANT", None, "I don't have that information available.",
     "EPHEMERAL — NOT PERSISTED"),
]

EVENT_LOG = [
    "MODEL READY",
    "SPEAKER: CAMERON (0.66) — PRIVATE ACCESS GRANTED "
    "[2.8S · -34 dBFS · EMBED 45 MS · STT 1080 MS]",
    "FACT SAVED (PRIVATE/CAMERON)",
    "SPEAKER: CAMERON (0.62) — PRIVATE ACCESS GRANTED "
    "[2.6S · -33 dBFS · EMBED 47 MS · STT 1110 MS]",
    "LLM REPLY (25 CHARS)",
    "SPEAKER: UNKNOWN (0.12) — BELOW THRESHOLD "
    "[2.9S · -33 dBFS · EMBED 44 MS · STT 1120 MS]",
    "LLM REPLY (36 CHARS)",
]

DEFAULT_CAPTURE = Path(__file__).resolve().parent.parent / "demo-out" / "audio-lab-demo.png"


def _fixed_waveform() -> np.ndarray:
    """A deterministic speech-like envelope — no randomness, reproducible."""
    t = np.linspace(0.0, 1.0, 600, dtype=np.float32)
    carrier = (
        0.5 * np.sin(2 * np.pi * 3 * t)
        + 0.3 * np.sin(2 * np.pi * 7 * t + 1.0)
        + 0.2 * np.sin(2 * np.pi * 13 * t + 2.0)
    )
    syllables = 0.5 + 0.5 * np.sin(2 * np.pi * 2.5 * t)  # amplitude modulation
    return (np.abs(carrier) * syllables * 0.8).astype(np.float32)


def _guest_debug_text() -> str:
    """The exact outbound request for the guest turn, built by the real
    router. The UNKNOWN/ephemeral path never touches a store, so store=None
    is safe here — and the private fact is structurally absent."""
    router = ContextRouter(store=None, ephemerals=EphemeralRegistry())
    decision = RecognitionDecision(
        tier=AccessTier.UNKNOWN,
        identity_id=None,
        display_name=None,
        similarity=0.12,
        second_best=0.08,
        reason="BELOW THRESHOLD",
    )
    bundle = router.route(decision, GUEST_QUESTION)
    request = build_request(bundle, GUEST_QUESTION, model="claude-opus-5")
    return f"{bundle.debug_summary}\n\n=== EXACT OUTBOUND REQUEST ===\n{request.serialized()}"


def build_demo_window() -> MainWindow:
    """Construct the real window in demo mode and populate every readout."""
    win = MainWindow(demo_mode=True)

    # microphone / interaction state — set directly; the mic is never opened
    win.panel.set_devices(
        [InputDevice(0, "MacBook Air Microphone", 48000.0, True)],
        "MacBook Air Microphone",
    )
    win.panel.set_armed(True)
    win.panel.show_state("MIC ARMED")
    win.panel.show_input_volume(75, low=False)
    win.panel.show_last_clip("2.9s  -33 dBFS", playable=False)
    win.ptt_button.setEnabled(True)
    win.waveform.set_state_text("MIC ARMED")
    win.waveform.set_level(0.42, -33.0)
    win.waveform.add_points(_fixed_waveform())

    # models + thresholds (values representative of our measurements)
    win.panel.show_model_state("MODEL READY")
    win.panel.set_thresholds(0.34, 0.44)

    # the conversation arc
    for label, similarity, text, tag in CONVERSATION:
        win.conversation.add_turn(label, similarity, text, tag)

    # readouts reflect the final (guest) turn — the current turn
    win.panel.show_speaker("SPEAKER  UNKNOWN", "SIM  0.12    2ND  0.08")
    win.panel.show_decision(
        "NO ACCESS — UNKNOWN SPEAKER", "BELOW THRESHOLD (0.12 < 0.34)", dimmed=True
    )
    win.panel.show_transcript(GUEST_QUESTION, "STT  1120 MS    EMBED   44 MS")
    win.panel.show_llm_state("LLM  CLAUDE-OPUS-5")
    win.panel.show_tts_state("TTS  IDLE", speaking=False)

    # DEBUG → SHOW LLM REQUEST: the exact guest request (54719 absent)
    win.panel.debug_check.setChecked(True)
    win.panel.set_debug_visible(True)
    win.panel.show_debug_request(_guest_debug_text())

    for line in EVENT_LOG:
        win.log_event(line)
    return win


def run_demo(capture_path: Path | None = None, auto_quit: bool = False) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(theme.stylesheet())
    win = build_demo_window()
    win.show()

    def _compose_and_capture() -> None:
        # scroll the right panel so DEBUG + EVENT LOG frame the shot
        bar = win._panel_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        if capture_path is not None:
            capture_path.parent.mkdir(parents=True, exist_ok=True)
            win.grab().save(str(capture_path))
            print(f"saved screenshot to {capture_path}")
        if auto_quit:
            app.quit()

    QTimer.singleShot(600, _compose_and_capture)
    return app.exec()
