"""Deterministic aggregation for scientific module compatibility."""

from __future__ import annotations

from typing import Literal

from ai4sota.domain import (
    CompatibilityState,
    DataModuleSpec,
    EvaluationSpec,
    MethodSpec,
    TaskContract,
)
from ai4sota.storage import canonical_manifest_hash

from .models import CompatibilityReport
from .rules import RULES

RULESET_VERSION: Literal["ai4sota/compatibility/v1"] = (
    "ai4sota/compatibility/v1"
)

STATE_RANK = {
    CompatibilityState.COMPATIBLE: 0,
    CompatibilityState.ADAPTABLE: 1,
    CompatibilityState.REQUIRES_DECISION: 2,
    CompatibilityState.INCOMPATIBLE: 3,
}


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
    contract_hash = canonical_manifest_hash(
        {
            "findings": [
                finding.model_dump(mode="json") for finding in findings
            ],
            "ruleset": RULESET_VERSION,
        }
    )
    return CompatibilityReport(
        ruleset_version=RULESET_VERSION,
        state=state,
        findings=findings,
        contract_hash=contract_hash,
    )


__all__ = ["RULESET_VERSION", "STATE_RANK", "compile_compatibility"]
