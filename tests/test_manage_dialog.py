"""ManageDialog: pure row formatting + contexts-tab mutations.

Widget-driving is kept minimal (Identity Lab style: prefer extracted pure
functions); the contexts operations are tested through the dialog's own
methods against real stores, since that is where the privacy-relevant
MAKE SHARED path lives.
"""

import pytest

from audio_lab.conversation.store import ConversationStore
from audio_lab.identity.store import IdentityStore
from audio_lab.ui.manage_dialog import ManageDialog, format_identity_row

MODEL = "speechbrain/spkrec-ecapa-voxceleb"


def test_format_identity_row():
    import datetime

    from audio_lab.identity.types import IdentityRecord

    rec = IdentityRecord(
        identity_id="x",
        display_name="Cameron",
        created_at=datetime.datetime(2026, 9, 20, 12, 0),
        enrollment_version=1,
        sample_count=6,
        model_id=MODEL,
        dim=192,
    )
    row = format_identity_row(rec)
    assert "Cameron" in row and "6 samples" in row and "2026-09-20" in row


@pytest.fixture()
def dialog(tmp_path, qt_core_app):
    import numpy as np

    speakers = IdentityStore(tmp_path / "speakers.db")
    cam = speakers.create_identity("Cameron")
    riley = speakers.create_identity("Riley")
    for s in (cam, riley):
        speakers.add_embedding_sample(
            s.identity_id, np.ones(192, dtype=np.float32), MODEL, 3.0
        )

    conv = ConversationStore(tmp_path / "conversations.db")
    conv.add_fact(conv.private_context_id(cam.identity_id), "Cam locker 4417", cam.identity_id)
    conv.add_fact(conv.private_context_id(riley.identity_id), "Riley diary green", riley.identity_id)

    dlg = ManageDialog(speakers, conversations=conv)
    yield dlg, speakers, conv, cam, riley
    dlg.close()
    speakers.close()
    conv.close()


class TestContextsTab:
    def test_lists_private_facts_per_speaker(self, dialog):
        dlg, _, _, _, _ = dialog
        rows = [dlg.facts_list.item(i).text() for i in range(dlg.facts_list.count())]
        assert any("Cameron" in r and "4417" in r for r in rows)
        assert any("Riley" in r and "green" in r for r in rows)

    def test_make_shared_copies_exactly_one_fact(self, dialog):
        dlg, _, conv, cam, _ = dialog
        shared_before = len(conv.facts(conv.shared_context_id()))
        # select Cameron's fact and share it
        idx = next(
            i for i in range(dlg.facts_list.count())
            if "4417" in dlg.facts_list.item(i).text()
        )
        dlg.facts_list.setCurrentRow(idx)
        dlg._make_shared()
        shared = conv.facts(conv.shared_context_id())
        assert len(shared) == shared_before + 1
        assert shared[-1].content == "Cam locker 4417"
        # original private fact untouched
        cam_facts = conv.facts(conv.private_context_id(cam.identity_id))
        assert any(f.content == "Cam locker 4417" for f in cam_facts)

    def test_delete_fact(self, dialog):
        dlg, _, conv, cam, _ = dialog
        idx = next(
            i for i in range(dlg.facts_list.count())
            if "4417" in dlg.facts_list.item(i).text()
        )
        dlg.facts_list.setCurrentRow(idx)
        dlg._delete_fact()
        assert conv.facts(conv.private_context_id(cam.identity_id)) == []

    def test_delete_speaker_drops_private_context(self, dialog):
        dlg, speakers, conv, cam, riley = dialog
        # delete Riley via the speakers-tab helper (confirm dialog bypassed by
        # calling the store path the dialog uses)
        speakers.delete_identity(riley.identity_id)
        conv.delete_speaker_data(riley.identity_id)
        assert conv.facts(conv.private_context_id(riley.identity_id)) == []
        # Cameron's data intact
        assert conv.facts(conv.private_context_id(cam.identity_id))
