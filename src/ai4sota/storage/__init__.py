"""Authoritative manifest persistence and disposable query indexing."""

from .atomic import (
    atomic_write_bytes,
    durable_make_directory,
    durable_replace,
    sync_directory_tree,
)
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
    "durable_make_directory",
    "durable_replace",
    "plan_schema_migration",
    "sync_directory_tree",
]
