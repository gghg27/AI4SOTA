from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai4sota.cli import main
from ai4sota.project import create_project
from ai4sota.runner import load_history, run_project
from ai4sota.validation import validate_project


class PhaseOneEndToEndTests(unittest.TestCase):
    def test_demo_project_full_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = create_project("demo", root, demo=True)

            dataset, report = validate_project(created.project_dir)
            self.assertEqual(len(dataset.sample_ids), 240)
            self.assertEqual(report["status"], "valid")
            self.assertEqual(report["splits"]["test"], 60)

            first = run_project(created.project_dir, note="first")
            second = run_project(created.project_dir, note="second")
            self.assertEqual(first["status"], "success")
            self.assertGreater(first["metrics"]["accuracy"], 0.70)

            history = load_history(created.project_dir)
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0]["note"], "second")
            self.assertTrue(
                (created.project_dir / "runs" / first["run_id"] / "metrics.json").is_file()
            )

    def test_cli_new_validate_run_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(main(["new", "cli-demo", "--output", str(root), "--demo"]), 0)
            project = root / "cli-demo"
            self.assertEqual(main(["validate", str(project)]), 0)
            self.assertEqual(main(["run", str(project), "--note", "cli"]), 0)
            self.assertEqual(main(["history", str(project)]), 0)

    def test_existing_target_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "demo").mkdir()
            with self.assertRaises(FileExistsError):
                create_project("demo", root, demo=True)

    def test_failed_run_is_preserved_in_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = create_project("demo", root, demo=True)
            method_file = created.project_dir / "method" / "model.py"
            method_file.write_text(
                method_file.read_text(encoding="utf-8").replace(
                    "def fit_predict(", "def renamed_fit_predict("
                ),
                encoding="utf-8",
            )

            with self.assertRaises(RuntimeError):
                run_project(created.project_dir, note="expected failure")
            history = load_history(created.project_dir)
            self.assertEqual(history[0]["status"], "failed")
            self.assertIn("fit_predict", history[0]["error"])


if __name__ == "__main__":
    unittest.main()
