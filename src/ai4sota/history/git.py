"""Small structured subprocess boundary for local Git operations."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitAdapter:
    """Run Git without invoking a command shell."""

    def run(self, cwd: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            text=True,
            capture_output=True,
        )
        return completed.stdout.strip()

    def ensure_repository(self, root: Path, initial_message: str) -> str:
        if not (root / ".git").exists():
            self.run(root, "init", "-b", "main")
        try:
            return self.run(root, "rev-parse", "--verify", "HEAD")
        except subprocess.CalledProcessError:
            self.run(root, "add", ".")
            self.run(root, "commit", "-m", initial_message)
            return self.run(root, "rev-parse", "--verify", "HEAD")


__all__ = ["GitAdapter"]
