"""Generate targeted corrections for confirmed-stale doc sections."""

from __future__ import annotations

from pydantic import ValidationError

from doc_sentinel.detection.models import StalenessVerdict, Suspect
from doc_sentinel.detection.verifier import _change_block
from doc_sentinel.llm.base import LLMClient
from doc_sentinel.repair.models import Correction

SYSTEM_PROMPT = """\
You are a surgical technical-documentation editor. You receive a documentation
section, the new version of the code it describes, and a diagnosis of exactly
what is stale. Produce a corrected version of the section.

Hard rules:
- Rewrite ONLY the parts named in the diagnosis. Every sentence that is still
  accurate must be preserved character for character.
- Preserve the original heading, structure, tone, formatting, and code-block
  style. Do not add new sections, notes, or commentary.
- Each edit's old_text must be copied verbatim from the original section.
- corrected_markdown must be the complete replacement for the section,
  starting with the same heading line.
"""


def build_user_prompt(suspect: Suspect, verdict: StalenessVerdict) -> str:
    changes = "\n".join(_change_block(c) for c in suspect.changes)
    diagnosis = "\n".join(
        f"- WRONG: {i.quote_from_docs!r}\n  BECAUSE: {i.what_is_wrong}\n"
        f"  CODE NOW: {i.what_code_says_now}"
        for i in verdict.issues
    )
    return (
        f"## New code\n{changes}\n"
        f"## Staleness diagnosis\n{diagnosis or '(no itemized issues; use the code changes)'}\n\n"
        f"## Original documentation section ({suspect.section.heading_display})\n"
        f"```markdown\n{suspect.section.content}\n```\n\n"
        "Produce the corrected section."
    )


def generate_correction(
    llm: LLMClient, suspect: Suspect, verdict: StalenessVerdict
) -> Correction | None:
    """One LLM call with a single validation retry; None means generation failed."""
    schema = Correction.model_json_schema()
    user = build_user_prompt(suspect, verdict)
    error_note = ""
    for _attempt in range(2):
        try:
            raw = llm.complete_structured(SYSTEM_PROMPT, user + error_note, schema, max_tokens=4096)
            correction = Correction.model_validate(raw)
        except (ValidationError, RuntimeError, ValueError) as exc:
            error_note = (
                "\n\nYour previous response was invalid and was discarded. "
                f"Validation error: {exc}. Respond again following the schema exactly."
            )
            continue
        bad = [e.old_text for e in correction.edits if e.old_text not in suspect.section.content]
        if bad:
            error_note = (
                "\n\nYour previous response was discarded because these old_text values "
                f"are not verbatim substrings of the original section: {bad!r}."
            )
            continue
        if not correction.corrected_markdown.strip():
            error_note = "\n\nYour previous response had an empty corrected_markdown."
            continue
        return correction
    return None
