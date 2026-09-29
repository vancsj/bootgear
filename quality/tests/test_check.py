from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from quality import check


class QualityCheckTests(unittest.TestCase):
    def test_run_checks_preserves_deterministic_command_order(self) -> None:
        calls: list[tuple[str, ...]] = []

        def execute(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        results = check._run_checks(execute)

        self.assertEqual([item.name for item in check.CHECKS], [item.check.name for item in results])
        self.assertEqual([item.command for item in check.CHECKS], calls)

    def test_run_checks_reports_missing_tool(self) -> None:
        def execute(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError("ruff")

        results = check._run_checks(execute)

        self.assertEqual(127, results[0].returncode)
        self.assertIn("FileNotFoundError", results[0].output)

    def test_report_accepts_matching_baseline(self) -> None:
        ruff = next(item for item in check.CHECKS if item.name == "ruff")
        result = check.Result(ruff, 1, "failure", check._fingerprint("failure"))
        baseline = [
            {
                "check": "ruff",
                "fingerprint": result.fingerprint,
                "identity": check._identity(),
            }
        ]

        self.assertEqual(0, check._report([result], baseline))

    def test_report_rejects_stale_baseline(self) -> None:
        result = check.Result(check.CHECKS[0], 0, "", check._fingerprint(""))
        baseline = [{"check": "ruff", "fingerprint": "old", "identity": "old"}]

        self.assertEqual(1, check._report([result], baseline))

    def test_main_rejects_wrong_repository_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            old = Path.cwd()
            try:
                os.chdir(directory)
                self.assertEqual(2, check.main())
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
