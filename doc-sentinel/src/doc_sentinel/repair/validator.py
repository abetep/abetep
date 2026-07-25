"""Quality gate: validate a generated correction before it can ship."""

from __future__ import annotations

import difflib

from pydantic import ValidationError

from doc_sentinel.detection.models import Suspect
from doc_sentinel.detection.verifier import _change_block
from doc_sentinel.llm.base import LLMClient
from doc_sentinel.repair.models import Correction, ValidationResult

SYSTEM_PROMPT = """\
You are a strict documentation reviewer acting as a quality gate. You receive
the new version of some code, the original documentation section, and a
proposed corrected section. Judge the correction:

- accurate: does the corrected section correctly describe the NEW code, with
  no remaining stale statements and no invented behavior?
- style_consistent: does it keep the original tone, formatting and structure?
- score: overall quality 0.0-1.0. A correction that is accurate, minimal and
  style-consistent scores >= 0.9. Any factual error caps the score at 0.3.
- reasons: short bullet points justifying the score.
"""


def preserved_ratio(original: str, corrected: str) -> float:
    """Fraction of original lines that survive verbatim in the corrected text.

    This is computed programmatically (difflib), not asked of the LLM, so the
    "don't rewrite what was correct" rule is enforced by code.
    """
    original_lines = [line for line in original.splitlines() if line.strip()]
    if not original_lines:
        return 1.0
    matcher = difflib.SequenceMatcher(
        a=original_lines,
        b=[line for line in corrected.splitlines() if line.strip()],
        autojunk=False,
    )
    kept = sum(block.size for block in matcher.get_matching_blocks())
    return kept / len(original_lines)


def build_user_prompt(suspect: Suspect, correction: Correction) -> str:
    changes = "\n".join(_change_block(c) for c in suspect.changes)
    return (
        f"## New code\n{changes}\n"
        f"## Original section\n```markdown\n{suspect.section.content}\n```\n\n"
        f"## Proposed corrected section\n```markdown\n{correction.corrected_markdown}\n```\n\n"
        "Evaluate the proposed correction."
    )


def validate_correction(
    llm: LLMClient, suspect: Suspect, correction: Correction
) -> ValidationResult | None:
    """LLM judgment plus the programmatic minimality measurement."""
    ratio = preserved_ratio(suspect.section.content, correction.corrected_markdown)
    schema = ValidationResult.model_json_schema()
    user = build_user_prompt(suspect, correction)
    error_note = ""
    for _attempt in range(2):
        try:
            raw = llm.complete_structured(SYSTEM_PROMPT, user + error_note, schema)
            raw.pop("preserved_ratio", None)  # programmatic field, never LLM-supplied
            result = ValidationResult.model_validate({**raw, "preserved_ratio": ratio})
            return result
        except (ValidationError, RuntimeError, ValueError) as exc:
            error_note = (
                "\n\nYour previous response was invalid and was discarded. "
                f"Validation error: {exc}. Respond again following the schema exactly."
            )
    return None
