"""The two-threshold recognition decision — the authorization core.

Pure function over a MatchResult. The matcher already enforces the
conversational-recognition threshold and the best-vs-second-best margin;
this layer adds the stricter private-access threshold on top.

Structural guarantee (pinned by tests): every failure branch yields a
strictly lower tier. Ambiguity, low scores, missing evidence — none of
them can ever *raise* privilege. A voiceprint is never authentication
(docs/threat-model.md); PRIVATE_VERIFIED means "confident enough to load
this person's context in a consenting household experiment."
"""

from dataclasses import dataclass
from enum import Enum

from audio_lab.identity.matcher import MatchResult

REASON_PRIVATE_GRANTED = "PRIVATE ACCESS GRANTED"


class AccessTier(str, Enum):
    PRIVATE_VERIFIED = "PRIVATE_VERIFIED"
    RECOGNIZED = "RECOGNIZED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RecognitionDecision:
    tier: AccessTier
    identity_id: str | None      # None iff UNKNOWN
    display_name: str | None
    similarity: float | None     # best score, reported even on UNKNOWN
    second_best: float | None
    reason: str                  # stable console string


def decide(
    match: MatchResult, *, private_access_threshold: float
) -> RecognitionDecision:
    """Map a match result onto an access tier.

    The matcher's own threshold is the conversational-recognition gate;
    private_access_threshold must be at or above it to be meaningful.
    """
    second = match.second_best.score if match.second_best is not None else None
    if not match.is_known:
        return RecognitionDecision(
            tier=AccessTier.UNKNOWN,
            identity_id=None,
            display_name=None,
            similarity=match.similarity,
            second_best=second,
            reason=match.reason,
        )
    if match.similarity >= private_access_threshold:
        return RecognitionDecision(
            tier=AccessTier.PRIVATE_VERIFIED,
            identity_id=match.identity_id,
            display_name=match.display_name,
            similarity=match.similarity,
            second_best=second,
            reason=REASON_PRIVATE_GRANTED,
        )
    return RecognitionDecision(
        tier=AccessTier.RECOGNIZED,
        identity_id=match.identity_id,
        display_name=match.display_name,
        similarity=match.similarity,
        second_best=second,
        reason=(
            f"BELOW PRIVATE THRESHOLD "
            f"({match.similarity:.2f} < {private_access_threshold:.2f})"
        ),
    )
