"""Convenience entry point for this generated project."""

from pathlib import Path

from ai4sota.runner import run_project


if __name__ == "__main__":
    record = run_project(Path(__file__).resolve().parent, note="pipeline.py run")
    print(record)

