"""Deterministic aggregation for scientific module compatibility."""

from __future__ import annotations

from ai4sota.domain import (
    DataModuleSpec,
    EvaluationSpec,
    MethodSpec,
    TaskContract,
)

from .models import (
    RULESET_VERSION,
    STATE_RANK,
    CompatibilityReport,
    compatibility_contract_hash,
)
from .rules import RULES


def compile_compatibility(
    data: DataModuleSpec,
    method: MethodSpec,
    evaluation: EvaluationSpec,
    task: TaskContract,
) -> CompatibilityReport:
    """Compile module contracts without executing code or consulting an LLM."""
    findings = tuple(
        rule(data, method, evaluation, task) for rule in RULES
    )
    state = max(
        (finding.state for finding in findings), key=STATE_RANK.__getitem__
    )
    contract_hash = compatibility_contract_hash(findings, RULESET_VERSION)
    return CompatibilityReport(
        ruleset_version=RULESET_VERSION,
        state=state,
        findings=findings,
        contract_hash=contract_hash,
    )


__all__ = ["RULESET_VERSION", "STATE_RANK", "compile_compatibility"]
