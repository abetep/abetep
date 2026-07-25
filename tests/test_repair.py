"""Phase 3 tests: generator guards, validator minimality, router modes, patcher."""

from pathlib import Path

from doc_sentinel.detection.models import (
    ChangeType,
    ChunkChange,
    StalenessIssue,
    StalenessVerdict,
    Suspect,
    VerifiedSuspect,
)
from doc_sentinel.indexing.code_parser import parse_repo
from doc_sentinel.indexing.doc_parser import parse_docs
from doc_sentinel.repair.models import (
    TODO_MARKER,
    Correction,
    DocEdit,
    RepairMode,
    SectionRepair,
    ValidationResult,
)
from doc_sentinel.repair.patcher import apply_repairs
from doc_sentinel.repair.router import RouterConfig, decide_mode
from doc_sentinel.repair.validator import preserved_ratio


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete_structured(self, system, user, schema, max_tokens=2048):
        self.calls.append(user)
        return self.responses.pop(0)


def make_suspect(mini_repo: Path, heading: str, chunk_name: str, change_type: ChangeType):
    chunks, _ = parse_repo(mini_repo, ["."], ["tests"])
    sections, _ = parse_docs(mini_repo, ["docs"], [])
    section = next(s for s in sections if s.heading_path[-1] == heading)
    chunk = next(c for c in chunks if c.name == chunk_name)
    change = ChunkChange(
        chunk_id=chunk.id,
        file=chunk.file,
        qualified_name=chunk.qualified_name,
        change_type=change_type,
        old_chunk=chunk,
        new_chunk=None if change_type == ChangeType.REMOVED else chunk,
    )
    return Suspect(section=section, changes=[change], score=1.0)


def stale_verdict(quote: str, confidence: float = 0.9) -> StalenessVerdict:
    return StalenessVerdict(
        is_stale=True,
        confidence=confidence,
        issues=[
            StalenessIssue(
                quote_from_docs=quote,
                what_is_wrong="renamed",
                what_code_says_now="parameter is embed_posts",
            )
        ],
    )


def test_generator_rejects_fabricated_old_text(mini_repo: Path) -> None:
    from doc_sentinel.repair.generator import generate_correction

    suspect = make_suspect(mini_repo, "Fetching users", "get_user", ChangeType.SIGNATURE_CHANGE)
    bad = {
        "corrected_markdown": "### Fetching users\n\nfixed",
        "edits": [{"old_text": "NOT IN SECTION", "new_text": "x", "reason": "r"}],
    }
    good = {
        "corrected_markdown": suspect.section.content.replace(
            "include_posts=True", "embed_posts=True"
        ),
        "edits": [
            {"old_text": "include_posts=True", "new_text": "embed_posts=True", "reason": "rename"}
        ],
    }
    llm = ScriptedLLM([bad, good])
    correction = generate_correction(llm, suspect, stale_verdict("include_posts=True"))
    assert correction is not None
    assert "embed_posts=True" in correction.corrected_markdown
    assert len(llm.calls) == 2 and "not verbatim substrings" in llm.calls[1]


def test_validator_computes_preserved_ratio_programmatically(mini_repo: Path) -> None:
    from doc_sentinel.repair.validator import validate_correction

    suspect = make_suspect(mini_repo, "Fetching users", "get_user", ChangeType.SIGNATURE_CHANGE)
    correction = Correction(
        corrected_markdown=suspect.section.content.replace("include_posts", "embed_posts"),
        edits=[],
    )
    # LLM tries to claim perfect preservation; the programmatic value must win
    llm = ScriptedLLM(
        [
            {
                "accurate": True,
                "style_consistent": True,
                "score": 0.95,
                "reasons": ["ok"],
                "preserved_ratio": 1.0,
            }
        ]
    )
    result = validate_correction(llm, suspect, correction)
    assert result is not None
    assert result.preserved_ratio < 1.0
    assert result.score == 0.95


def test_preserved_ratio_full_rewrite_is_low() -> None:
    original = "### T\n\nline one\nline two\nline three\n"
    assert preserved_ratio(original, original) == 1.0
    assert preserved_ratio(original, "### T\n\ncompletely different\n") < 0.5


def router_inputs(mini_repo: Path, change_type: ChangeType, confidence: float):
    suspect = make_suspect(mini_repo, "Fetching users", "get_user", change_type)
    verdict = stale_verdict("include_posts=True", confidence=confidence)
    return VerifiedSuspect(suspect=suspect, verdict=verdict)


def test_router_auto_fixes_simple_high_confidence(mini_repo: Path) -> None:
    verified = router_inputs(mini_repo, ChangeType.SIGNATURE_CHANGE, 0.95)
    validation = ValidationResult(
        accurate=True, style_consistent=True, score=0.92, preserved_ratio=0.9
    )
    assert decide_mode(verified, validation, RouterConfig()) == RepairMode.AUTO_FIX


def test_router_drafts_complex_changes_even_with_high_scores(mini_repo: Path) -> None:
    verified = router_inputs(mini_repo, ChangeType.REMOVED, 0.95)
    validation = ValidationResult(
        accurate=True, style_consistent=True, score=0.95, preserved_ratio=0.9
    )
    assert decide_mode(verified, validation, RouterConfig()) == RepairMode.DRAFT_WITH_TODOS


def test_router_flags_low_confidence_and_failed_validation(mini_repo: Path) -> None:
    low_conf = router_inputs(mini_repo, ChangeType.SIGNATURE_CHANGE, 0.4)
    weak_validation = ValidationResult(
        accurate=True, style_consistent=True, score=0.4, preserved_ratio=0.9
    )
    assert decide_mode(low_conf, weak_validation, RouterConfig()) == RepairMode.FLAG_ONLY

    verified = router_inputs(mini_repo, ChangeType.SIGNATURE_CHANGE, 0.95)
    assert decide_mode(verified, None, RouterConfig()) == RepairMode.FLAG_ONLY
    inaccurate = ValidationResult(
        accurate=False, style_consistent=True, score=0.9, preserved_ratio=0.9
    )
    assert decide_mode(verified, inaccurate, RouterConfig()) == RepairMode.FLAG_ONLY


def test_router_flags_unverified(mini_repo: Path) -> None:
    suspect = make_suspect(mini_repo, "Fetching users", "get_user", ChangeType.SIGNATURE_CHANGE)
    verified = VerifiedSuspect(suspect=suspect, verdict=None)
    assert decide_mode(verified, None, RouterConfig()) == RepairMode.FLAG_ONLY


def test_patcher_end_to_end_preserves_untouched_sections(mini_repo: Path) -> None:
    suspect = make_suspect(mini_repo, "Fetching users", "get_user", ChangeType.SIGNATURE_CHANGE)
    original_doc = (mini_repo / "docs" / "usage.md").read_text()
    corrected = suspect.section.content.replace("include_posts=True", "embed_posts=True")
    repair = SectionRepair(
        verified=VerifiedSuspect(suspect=suspect, verdict=stale_verdict("include_posts=True")),
        mode=RepairMode.AUTO_FIX,
        correction=Correction(
            corrected_markdown=corrected,
            edits=[DocEdit(old_text="include_posts=True", new_text="embed_posts=True", reason="")],
        ),
        validation=ValidationResult(
            accurate=True, style_consistent=True, score=0.95, preserved_ratio=0.95
        ),
    )
    results = apply_repairs(mini_repo, [repair])
    new_doc = results["docs/usage.md"]
    assert "embed_posts=True" in new_doc and "include_posts=True" not in new_doc
    # every other section byte-identical
    for line in original_doc.splitlines():
        if "include_posts" not in line:
            assert line in new_doc.splitlines()
    # sections after the patched one keep their content
    assert "`timeout_seconds` is 30" in new_doc


def test_patcher_injects_todo_marker_for_drafts(mini_repo: Path) -> None:
    suspect = make_suspect(mini_repo, "Formatting", "format_username", ChangeType.REMOVED)
    repair = SectionRepair(
        verified=VerifiedSuspect(suspect=suspect, verdict=stale_verdict("format_username")),
        mode=RepairMode.DRAFT_WITH_TODOS,
        correction=Correction(corrected_markdown="### Formatting\n\nThis helper was removed."),
    )
    results = apply_repairs(mini_repo, [repair])
    new_doc = results["docs/usage.md"]
    assert TODO_MARKER in new_doc
    assert new_doc.index("### Formatting") < new_doc.index(TODO_MARKER)


def test_engine_full_pipeline_with_mocked_llm(mini_repo: Path) -> None:
    """index -> check(mocked) -> repair(mocked) -> patch, on the fixture repo."""
    from doc_sentinel.detection.models import CheckReport
    from doc_sentinel.repair.engine import repair_sections

    suspect = make_suspect(mini_repo, "Fetching users", "get_user", ChangeType.SIGNATURE_CHANGE)
    check = CheckReport(
        base_ref="HEAD~1",
        head_ref="HEAD",
        changes=suspect.changes,
        verified=[VerifiedSuspect(suspect=suspect, verdict=stale_verdict("include_posts=True"))],
    )
    corrected = suspect.section.content.replace("include_posts=True", "embed_posts=True")
    llm = ScriptedLLM(
        [
            {  # generator
                "corrected_markdown": corrected,
                "edits": [
                    {
                        "old_text": "include_posts=True",
                        "new_text": "embed_posts=True",
                        "reason": "r",
                    }
                ],
            },
            {  # validator
                "accurate": True,
                "style_consistent": True,
                "score": 0.93,
                "reasons": ["accurate and minimal"],
            },
        ]
    )
    report = repair_sections(llm, check)
    assert [r.mode for r in report.repairs] == [RepairMode.AUTO_FIX]
    results = apply_repairs(mini_repo, report.repairs)
    assert "embed_posts=True" in results["docs/usage.md"]
