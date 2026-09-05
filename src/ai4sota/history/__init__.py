"""Exact-snapshot research history backed by Git and manifests."""

from .git import GitAdapter
from .research_commits import ResearchCommitError, create_research_commit

__all__ = ["GitAdapter", "ResearchCommitError", "create_research_commit"]
