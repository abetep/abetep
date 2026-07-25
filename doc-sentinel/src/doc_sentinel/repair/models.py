"""Models for the doc repair engine."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from doc_sentinel.detection.models import VerifiedSuspect

TODO_MARKER = "<!-- TODO(doc-sentinel): human review needed -->"


class DocEdit(BaseModel):
    old_text: str = Field(description="Exact substring of the original section being replaced")
    new_text: str
    reason: str


class Correction(BaseModel):
    corrected_markdown: str = Field(description="Full replacement content for the section")
    edits: list[DocEdit] = Field(default_factory=list)


class ValidationResult(BaseModel):
    accurate: bool
    style_consistent: bool
    score: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    # Programmatic check, not LLM opinion: ratio of original lines preserved
    # outside the spans the diagnosis flagged.
    preserved_ratio: float = Field(ge=0.0, le=1.0, default=1.0)


class RepairMode(StrEnum):
    AUTO_FIX = "auto_fix"
    DRAFT_WITH_TODOS = "draft_with_todos"
    FLAG_ONLY = "flag_only"


class SectionRepair(BaseModel):
    verified: VerifiedSuspect
    mode: RepairMode
    correction: Correction | None = None
    validation: ValidationResult | None = None

    @property
    def section_id(self) -> str:
        return self.verified.suspect.section.id


class RepairReport(BaseModel):
    repairs: list[SectionRepair] = Field(default_factory=list)

    def by_mode(self, mode: RepairMode) -> list[SectionRepair]:
        return [r for r in self.repairs if r.mode == mode]
