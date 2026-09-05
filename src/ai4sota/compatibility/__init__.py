"""Deterministic scientific compatibility compilation."""

from .compiler import RULESET_VERSION, STATE_RANK, compile_compatibility
from .models import (
    AdapterKind,
    CompatibilityFinding,
    CompatibilityReport,
    MechanicalAdapterSpec,
)

__all__ = [
    "RULESET_VERSION",
    "STATE_RANK",
    "AdapterKind",
    "CompatibilityFinding",
    "CompatibilityReport",
    "MechanicalAdapterSpec",
    "compile_compatibility",
]
