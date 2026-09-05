"""Versioned scientific domain contracts for AI4SOTA."""

from .common import (
    ComparabilityState,
    CompatibilityState,
    ConversationScope,
    ModuleKind,
    SchemaHeader,
)
from .decisions import DecisionRecord
from .experiments import (
    ExperimentSpec,
    ResearchCommitManifest,
    RunManifest,
    SplitManifest,
)
from .modules import (
    DataModuleSpec,
    DatasetSourceSpec,
    EvaluationSpec,
    MethodSpec,
    PreprocessingSpec,
)
from .projects import ProjectSpec
from .task import TaskContract

__all__ = [
    "ComparabilityState",
    "CompatibilityState",
    "ConversationScope",
    "DataModuleSpec",
    "DatasetSourceSpec",
    "DecisionRecord",
    "EvaluationSpec",
    "ExperimentSpec",
    "MethodSpec",
    "ModuleKind",
    "PreprocessingSpec",
    "ProjectSpec",
    "ResearchCommitManifest",
    "RunManifest",
    "SchemaHeader",
    "SplitManifest",
    "TaskContract",
]
