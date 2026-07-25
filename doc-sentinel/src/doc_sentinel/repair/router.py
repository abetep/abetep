"""Route each stale section to auto-fix, draft-with-TODOs, or flag-only."""

from __future__ import annotations

from pydantic import BaseModel

from doc_sentinel.detection.models import ChangeType, VerifiedSuspect
from doc_sentinel.repair.models import RepairMode, ValidationResult

# Changes simple enough to auto-fix when confidence is high: renames,
# signature tweaks, changed defaults. New/removed capabilities always
# need a human in the loop.
SIMPLE_CHANGES = {
    ChangeType.SIGNATURE_CHANGE,
    ChangeType.CONFIG_CHANGE,
    ChangeType.BEHAVIOR_CHANGE,
}
COMPLEX_CHANGES = {ChangeType.ADDED, ChangeType.REMOVED}


class RouterConfig(BaseModel):
    auto_fix_confidence: float = 0.8
    auto_fix_validation_score: float = 0.8
    min_preserved_ratio: float = 0.35
    draft_validation_score: float = 0.5


def decide_mode(
    verified: VerifiedSuspect,
    validation: ValidationResult | None,
    config: RouterConfig,
) -> RepairMode:
    verdict = verified.verdict
    if verdict is None or not verdict.is_stale:
        return RepairMode.FLAG_ONLY
    if validation is None or not validation.accurate:
        return RepairMode.FLAG_ONLY
    if validation.score < config.draft_validation_score:
        return RepairMode.FLAG_ONLY

    change_types = {c.change_type for c in verified.suspect.changes}
    is_simple = change_types <= SIMPLE_CHANGES
    high_confidence = (
        verdict.confidence >= config.auto_fix_confidence
        and validation.score >= config.auto_fix_validation_score
        and validation.preserved_ratio >= config.min_preserved_ratio
        and validation.style_consistent
    )
    if is_simple and high_confidence:
        return RepairMode.AUTO_FIX
    return RepairMode.DRAFT_WITH_TODOS
