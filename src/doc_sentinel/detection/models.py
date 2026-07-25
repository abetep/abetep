"""Models for the change-detection pipeline."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from doc_sentinel.models import CodeChunk, DocSection


class ChangeType(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    SIGNATURE_CHANGE = "signature_change"
    CONFIG_CHANGE = "config_change"
    BEHAVIOR_CHANGE = "behavior_change"
    COSMETIC = "cosmetic"


MEANINGFUL_CHANGES = {
    ChangeType.ADDED,
    ChangeType.REMOVED,
    ChangeType.SIGNATURE_CHANGE,
    ChangeType.CONFIG_CHANGE,
    ChangeType.BEHAVIOR_CHANGE,
}


class ChunkChange(BaseModel):
    chunk_id: str
    file: str
    qualified_name: str
    change_type: ChangeType
    old_chunk: CodeChunk | None = None
    new_chunk: CodeChunk | None = None

    def describe(self) -> str:
        if self.change_type == ChangeType.ADDED:
            return f"`{self.qualified_name}` was added"
        if self.change_type == ChangeType.REMOVED:
            return f"`{self.qualified_name}` was removed"
        return f"`{self.qualified_name}`: {self.change_type.value.replace('_', ' ')}"


class Suspect(BaseModel):
    """A doc section that might be stale, with the changes implicating it."""

    section: DocSection
    changes: list[ChunkChange]
    score: float


class StalenessIssue(BaseModel):
    quote_from_docs: str = Field(description="Exact substring of the doc section that is wrong")
    what_is_wrong: str
    what_code_says_now: str


class StalenessVerdict(BaseModel):
    is_stale: bool
    confidence: float = Field(ge=0.0, le=1.0)
    issues: list[StalenessIssue] = Field(default_factory=list)


class VerifiedSuspect(BaseModel):
    suspect: Suspect
    verdict: StalenessVerdict | None = None  # None: LLM verification failed -> flag for review


class CheckReport(BaseModel):
    base_ref: str
    head_ref: str
    changes: list[ChunkChange]
    verified: list[VerifiedSuspect]

    @property
    def stale(self) -> list[VerifiedSuspect]:
        return [v for v in self.verified if v.verdict is not None and v.verdict.is_stale]

    @property
    def accurate(self) -> list[VerifiedSuspect]:
        return [v for v in self.verified if v.verdict is not None and not v.verdict.is_stale]

    @property
    def unverified(self) -> list[VerifiedSuspect]:
        return [v for v in self.verified if v.verdict is None]
