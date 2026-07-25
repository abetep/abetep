"""Orchestrate generate -> validate -> route for every stale section."""

from __future__ import annotations

from doc_sentinel.detection.models import CheckReport
from doc_sentinel.llm.base import LLMClient
from doc_sentinel.repair.generator import generate_correction
from doc_sentinel.repair.models import RepairMode, RepairReport, SectionRepair
from doc_sentinel.repair.router import RouterConfig, decide_mode
from doc_sentinel.repair.validator import validate_correction


def repair_sections(
    llm: LLMClient, check: CheckReport, config: RouterConfig | None = None
) -> RepairReport:
    config = config or RouterConfig()
    repairs: list[SectionRepair] = []
    for verified in check.stale:
        assert verified.verdict is not None
        correction = generate_correction(llm, verified.suspect, verified.verdict)
        validation = None
        if correction is not None:
            validation = validate_correction(llm, verified.suspect, correction)
        mode = decide_mode(verified, validation, config)
        repairs.append(
            SectionRepair(
                verified=verified, mode=mode, correction=correction, validation=validation
            )
        )
    for verified in check.unverified:
        repairs.append(SectionRepair(verified=verified, mode=RepairMode.FLAG_ONLY))
    return RepairReport(repairs=repairs)
