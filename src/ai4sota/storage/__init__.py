"""Authoritative manifest persistence and disposable query indexing."""

from .atomic import atomic_write_bytes
from .index import ResearchIndex
from .manifests import ManifestStore, canonical_manifest_hash
from .migrations import (
    MigrationPlan,
    apply_schema_migration,
    plan_schema_migration,
)

__all__ = [
    "ManifestStore",
    "MigrationPlan",
    "ResearchIndex",
    "apply_schema_migration",
    "atomic_write_bytes",
    "canonical_manifest_hash",
    "plan_schema_migration",
]
