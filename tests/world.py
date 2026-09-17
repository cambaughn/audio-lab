"""Shared privacy-test world: two speakers, canaries everywhere.

Canary strings are high-entropy so accidental appearance is impossible;
if one shows up in a serialized request, it was routed there.
"""

from audio_lab.conversation.ephemeral import GUEST_KEY, EphemeralRegistry
from audio_lab.conversation.router import ContextRouter
from audio_lab.conversation.store import ConversationStore
from audio_lab.identity.decision import AccessTier, RecognitionDecision
from audio_lab.llm.types import LlmMessage

CAM_ID = "cam-id-001"
RILEY_ID = "riley-id-002"

CANARY_CAM_PRIV = "CANARY-CAM-PRIV-9f3ax7"
CANARY_CAM_HIST = "CANARY-CAM-HIST-2k8jq1"
CANARY_RILEY_PRIV = "CANARY-RILEY-PRIV-5t1mw4"
CANARY_RILEY_HIST = "CANARY-RILEY-HIST-7d4qn8"
CANARY_SHARED = "CANARY-SHARED-8r2pz6"
CANARY_GUEST = "CANARY-GUEST-3v9nc2"


def decision(tier: AccessTier, speaker: str | None = None) -> RecognitionDecision:
    names = {CAM_ID: "Cameron", RILEY_ID: "Riley"}
    return RecognitionDecision(
        tier=tier,
        identity_id=speaker if tier is not AccessTier.UNKNOWN else None,
        display_name=names.get(speaker) if tier is not AccessTier.UNKNOWN else None,
        similarity=0.7 if tier is AccessTier.PRIVATE_VERIFIED else 0.45,
        second_best=0.1,
        reason="TEST",
    )


ALL_DECISIONS = {
    "PV(cam)": decision(AccessTier.PRIVATE_VERIFIED, CAM_ID),
    "PV(riley)": decision(AccessTier.PRIVATE_VERIFIED, RILEY_ID),
    "REC(cam)": decision(AccessTier.RECOGNIZED, CAM_ID),
    "REC(riley)": decision(AccessTier.RECOGNIZED, RILEY_ID),
    "UNKNOWN": decision(AccessTier.UNKNOWN),
}


def make_world(tmp_path):
    """Seed a store + ephemerals with every canary. Returns
    (store, ephemerals, router)."""
    store = ConversationStore(tmp_path / "conversations.db")
    ephemerals = EphemeralRegistry()
    router = ContextRouter(store, ephemerals)

    cam_ctx = store.private_context_id(CAM_ID)
    store.add_fact(cam_ctx, f"Cameron's locker code is {CANARY_CAM_PRIV}", CAM_ID)
    store.add_message(cam_ctx, "user", f"I once said {CANARY_CAM_HIST}", speaker_id=CAM_ID)
    store.add_message(cam_ctx, "assistant", "Noted.")

    riley_ctx = store.private_context_id(RILEY_ID)
    store.add_fact(riley_ctx, f"Riley's diary hint is {CANARY_RILEY_PRIV}", RILEY_ID)
    store.add_message(riley_ctx, "user", f"My secret phrase is {CANARY_RILEY_HIST}", speaker_id=RILEY_ID)
    store.add_message(riley_ctx, "assistant", "Understood.")

    store.add_fact(store.shared_context_id(), f"The wifi password is {CANARY_SHARED}", CAM_ID)

    guest = ephemerals.session_for(GUEST_KEY)
    guest.messages.append(LlmMessage(role="user", content=f"Guest said {CANARY_GUEST}"))

    return store, ephemerals, router
