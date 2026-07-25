"""LLM verification of whether a suspect doc section is actually stale."""

from __future__ import annotations

from pydantic import ValidationError

from doc_sentinel.detection.models import (
    ChangeType,
    ChunkChange,
    StalenessVerdict,
    Suspect,
    VerifiedSuspect,
)
from doc_sentinel.llm.base import LLMClient

SYSTEM_PROMPT = """\
You are a meticulous documentation reviewer. You are given a code change
(old and new versions of the affected code) and one documentation section.
Decide whether the documentation is still accurate AFTER the code change.

Rules:
- Judge only this section against this code. Do not speculate about other docs.
- The section is stale only if something it states is now wrong or missing
  in a way that would mislead a reader (renamed/removed parameters, changed
  defaults, changed behavior, removed features, wrong endpoints).
- Style, phrasing, and omissions of brand-new optional features do NOT make
  a section stale unless the section contradicts the new code.
- Every `quote_from_docs` MUST be copied verbatim from the documentation
  section, character for character.
- confidence is your certainty in the is_stale judgment (0.0-1.0).
"""


def _change_block(change: ChunkChange) -> str:
    old = change.old_chunk.source if change.old_chunk else "(did not exist)"
    new = change.new_chunk.source if change.new_chunk else "(deleted)"
    return (
        f"### Change: {change.describe()}\n"
        f"OLD CODE:\n```python\n{old}\n```\n"
        f"NEW CODE:\n```python\n{new}\n```\n"
    )


def build_user_prompt(suspect: Suspect) -> str:
    changes = "\n".join(_change_block(c) for c in suspect.changes)
    return (
        f"## Code changes\n{changes}\n"
        f"## Documentation section: {suspect.section.heading_display} "
        f"({suspect.section.file})\n"
        f"```markdown\n{suspect.section.content}\n```\n\n"
        "Is this section still accurate after the change?"
    )


def _bad_quotes(verdict: StalenessVerdict, section_content: str) -> list[str]:
    return [i.quote_from_docs for i in verdict.issues if i.quote_from_docs not in section_content]


def verify_suspect(llm: LLMClient, suspect: Suspect) -> VerifiedSuspect:
    """One LLM call (with a single validation retry) per suspect section.

    Returns a VerifiedSuspect whose verdict is None when the LLM could not
    produce a valid response; callers must treat that as "flag for human
    review", never as "accurate".
    """
    schema = StalenessVerdict.model_json_schema()
    user = build_user_prompt(suspect)
    error_note = ""
    for _attempt in range(2):
        try:
            raw = llm.complete_structured(SYSTEM_PROMPT, user + error_note, schema)
            verdict = StalenessVerdict.model_validate(raw)
        except (ValidationError, RuntimeError, ValueError) as exc:
            error_note = (
                "\n\nYour previous response was invalid and was discarded. "
                f"Validation error: {exc}. Respond again following the schema exactly."
            )
            continue
        bad = _bad_quotes(verdict, suspect.section.content)
        if bad:
            error_note = (
                "\n\nYour previous response was discarded because these "
                f"quote_from_docs values are not verbatim substrings of the section: {bad!r}. "
                "Copy quotes exactly from the documentation section."
            )
            continue
        return VerifiedSuspect(suspect=suspect, verdict=verdict)
    return VerifiedSuspect(suspect=suspect, verdict=None)


def verify_all(llm: LLMClient, suspects: list[Suspect]) -> list[VerifiedSuspect]:
    return [verify_suspect(llm, s) for s in suspects]


def removal_note(suspect: Suspect) -> bool:
    """True when every implicating change is a removal (docs must be rewritten by a human)."""
    return all(c.change_type == ChangeType.REMOVED for c in suspect.changes)
