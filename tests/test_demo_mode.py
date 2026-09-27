"""Demo mode is inert developer tooling: no mic/model/network/DB, no
persistence, and the guest LLM request never contains the private fact."""

import audio_lab.ui.main_window as mw
from audio_lab.demo import build_demo_window


class TestNoRealSubsystems:
    def test_no_stores_workers_or_mic(self, qt_core_app):
        win = build_demo_window()
        try:
            # no databases opened
            assert win.store is None
            assert win.conversations is None
            assert win.router is None
            # no model / network threads started
            assert win.speech_worker is None
            assert win.llm_worker is None
            assert win._speech_thread is None
            assert win._llm_thread is None
            # the microphone was never opened (no stream created)
            assert win.recorder._stream is None
        finally:
            win.close()

    def test_does_not_open_any_database(self, qt_core_app, monkeypatch):
        # if demo mode tried to construct either store, this raises
        def boom(*args, **kwargs):
            raise AssertionError("demo mode opened a database")

        monkeypatch.setattr(mw, "IdentityStore", boom)
        monkeypatch.setattr(mw, "ConversationStore", boom)
        win = build_demo_window()
        win.close()  # reaching here means neither store was constructed

    def test_persists_nothing_on_close(self, qt_core_app, monkeypatch):
        import audio_lab.config.settings as settings

        def boom(*args, **kwargs):
            raise AssertionError("demo mode persisted settings")

        monkeypatch.setattr(settings, "save_settings", boom)
        win = build_demo_window()
        win.close()  # closeEvent must not write settings in demo mode


class TestDeterministicState:
    def test_conversation_arc_present(self, qt_core_app):
        win = build_demo_window()
        try:
            convo = win.conversation.toPlainText()
            assert "Remember my spaceship code is 54719." in convo
            assert "Your spaceship code is 54719." in convo
            assert "[CAMERON 0.66]" in convo
            assert "[UNKNOWN 0.12 · EPHEMERAL — NOT PERSISTED]" in convo
        finally:
            win.close()

    def test_readouts_reflect_guest_turn(self, qt_core_app):
        win = build_demo_window()
        try:
            assert "UNKNOWN" in win.panel.speaker_label.text()
            assert "0.12" in win.panel.similarity_label.text()
            assert "UNKNOWN" in win.panel.decision_label.text()
            # debug view is un-hidden (isVisible() would need a shown window)
            assert not win.panel.debug_view.isHidden()
        finally:
            win.close()

    def test_waveform_is_deterministic(self, qt_core_app):
        # same content twice — no randomness anywhere in demo population
        a = build_demo_window()
        b = build_demo_window()
        try:
            assert a.conversation.toPlainText() == b.conversation.toPlainText()
            assert a.panel.debug_view.toPlainText() == b.panel.debug_view.toPlainText()
        finally:
            a.close()
            b.close()


class TestPrivacyGuaranteeInScreenshot:
    def test_guest_request_excludes_the_secret(self, qt_core_app):
        win = build_demo_window()
        try:
            debug = win.panel.debug_view.toPlainText()
            # the guest's exact outbound request is shown...
            assert "unidentified guest" in debug
            assert "EPHEMERAL" in debug
            assert "What's Cameron's spaceship code?" in debug
            # ...and the private fact is absent from it — the whole point
            assert "54719" not in debug
            # while the secret plainly DID exist in the conversation
            assert "54719" in win.conversation.toPlainText()
        finally:
            win.close()
