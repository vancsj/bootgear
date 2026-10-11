"""The third ledger kind, `deputy`: constants, root resolution and the default open set.

Every run is a subprocess against temp ledger roots; nothing here touches a real ledger.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "scripts"))

from ledgerlib import constants  # noqa: E402
from ledgerlib.config import open_ledgers  # noqa: E402


class DeputyConstantTest(unittest.TestCase):
    def test_deputy_is_a_kind_with_a_default_root(self) -> None:
        self.assertEqual(constants.DEPUTY, "deputy")
        self.assertEqual(constants.KINDS, (constants.SHARED, constants.LOCAL, constants.DEPUTY))
        self.assertEqual(constants.DEFAULT_DEPUTY_ROOT, "~/.memory-ledger/deputy")


LEDGER = PLUGIN / "scripts" / "ledger.py"


def run_ledger(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(LEDGER), *args], capture_output=True, text=True)


def init_root(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    return path


class DeputyWriteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.shared = init_root(base / "shared")
        self.local = init_root(base / "local")
        self.deputy = init_root(base / "deputy")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def roots(self) -> list[str]:
        return ["--root", str(self.shared), "--local-root", str(self.local),
                "--deputy-root", str(self.deputy)]

    def new(self, *extra: str) -> subprocess.CompletedProcess:
        return run_ledger(*self.roots(), "new", "deputy-probe", "--q", "Is X allowed?",
                          "--claim", "X is allowed", "--because", "Because: test. Context: none.",
                          "--evidence", "true", *extra)

    def test_new_deputy_writes_to_the_deputy_root_while_shared_and_local_are_open(self) -> None:
        r = self.new("--deputy")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(list(self.deputy.rglob("deputy-probe.md")))
        self.assertFalse(list(self.shared.rglob("deputy-probe.md")))
        self.assertFalse(list(self.local.rglob("deputy-probe.md")))

    def test_three_ledgers_open_without_a_flag_refuses_and_writes_nothing(self) -> None:
        r = self.new()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("say which ledger", r.stderr)
        self.assertFalse(list(self.deputy.rglob("deputy-probe.md")))

    def test_new_deputy_refuses_when_the_deputy_root_is_absent(self) -> None:
        shutil.rmtree(self.deputy)
        r = self.new("--deputy")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no deputy ledger", r.stderr)
        self.assertFalse(list(self.shared.rglob("deputy-probe.md")))
        self.assertFalse(list(self.local.rglob("deputy-probe.md")))

    def test_new_deputy_refuses_when_only_shared_is_open(self) -> None:
        shutil.rmtree(self.deputy)
        shutil.rmtree(self.local)
        r = self.new("--deputy")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no deputy ledger", r.stderr)
        self.assertFalse(list(self.shared.rglob("deputy-probe.md")))

    def test_deputy_root_equal_to_shared_refuses_and_writes_nothing(self) -> None:
        r = run_ledger("--root", str(self.shared), "--local-root", str(self.local),
                       "--deputy-root", str(self.shared), "new", "deputy-probe", "--q",
                       "Is X allowed?", "--claim", "X is allowed", "--because",
                       "Because: test. Context: none.", "--evidence", "true", "--deputy")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("same path", r.stderr)
        self.assertFalse(list(self.shared.rglob("deputy-probe.md")))

    def test_single_open_ledger_without_a_flag_still_takes_the_entry(self) -> None:
        shutil.rmtree(self.deputy)
        shutil.rmtree(self.local)
        r = self.new()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(list(self.shared.rglob("deputy-probe.md")))


class DeputySetupTest(unittest.TestCase):
    def test_setup_steps_create_the_deputy_ledger_with_its_charter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            shared, local = init_root(base / "shared"), init_root(base / "local")
            deputy = base / "deputy"
            subprocess.run(["git", "init", "-q", str(deputy)], check=True)
            (deputy / ".gitignore").write_text(".ledger-cache.json\n", encoding="utf-8")
            roots = ["--root", str(shared), "--local-root", str(local),
                     "--deputy-root", str(deputy)]
            seeded = run_ledger(*roots, "rules", "--init", "--only", "deputy")
            self.assertEqual(seeded.returncode, 0, seeded.stderr)
            self.assertTrue((deputy / "WHAT-BELONGS.txt").is_file())
            charter = run_ledger(*roots, "new", "decisions/_about", "--deputy",
                                 "--q", "What belongs here?", "--claim", "Decisions the user made",
                                 "--because", "Because: setup test. Context: none.",
                                 "--evidence", "true")
            self.assertEqual(charter.returncode, 0, charter.stderr)
            self.assertTrue((deputy / "decisions" / "_about.md").is_file())
            lint = run_ledger(*roots, "lint", "--only", "deputy")
            self.assertNotIn("NO-ABOUT", lint.stdout, lint.stdout)


class DeputySelftestTest(unittest.TestCase):
    def test_selftest_checks_the_deputy_root_and_exits_zero(self) -> None:
        r = subprocess.run([sys.executable, str(LEDGER), "selftest"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-400:])
        self.assertIn("deputy: the default open set excludes the deputy root", r.stdout)


class DeputyLocalOnlyTest(unittest.TestCase):
    def test_deputy_entry_may_name_a_machine_path_and_audit_does_not_flag_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            shared, local = init_root(base / "shared"), init_root(base / "local")
            deputy = init_root(base / "deputy")
            roots = ["--root", str(shared), "--local-root", str(local),
                     "--deputy-root", str(deputy)]
            machine_path = f"test -f {Path.home()}/.bootgear/session/run.md"
            r = run_ledger(*roots, "new", "deputy-path", "--q", "Where is the session?",
                           "--claim", "The session file is in the session directory",
                           "--because", "Because: test. Context: none.",
                           "--evidence", machine_path, "--deputy")
            self.assertEqual(r.returncode, 0, r.stderr)
            audit = run_ledger(*roots, "audit", "--only", "deputy")
            self.assertNotIn("UNPORTABLE", audit.stdout, audit.stdout)


class DeputyRootsReportTest(unittest.TestCase):
    def test_resolve_roots_reports_the_deputy_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            r = run_ledger("--root", str(base / "shared"), "--local-root", str(base / "local"),
                           "--deputy-root", str(base / "deputy"), "resolve-roots")
            self.assertEqual(r.returncode, 0, r.stderr)
            lines = [line.split() for line in r.stdout.splitlines() if line.strip()]
            self.assertEqual([row[0] for row in lines], ["shared", "local", "deputy"], r.stdout)
            self.assertEqual(lines[2][1], str(base / "deputy"))


class DeputyDoctorTest(unittest.TestCase):
    def doctor(self, shared: Path, local: Path, deputy: Path) -> dict:
        r = run_ledger("--root", str(shared), "--local-root", str(local),
                       "--deputy-root", str(deputy), "doctor", "--json")
        return json.loads(r.stdout)

    def deputy_warnings(self, report: dict) -> list[str]:
        return [w for w in report["warnings"] if w.startswith("deputy ledger")]

    def test_missing_deputy_root_warns_and_leaves_capability_status_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            shared, local = init_root(base / "shared"), init_root(base / "local")
            with_root = init_root(base / "deputy")
            present = self.doctor(shared, local, with_root)
            shutil.rmtree(with_root)
            missing = self.doctor(shared, local, base / "deputy")
            self.assertEqual(len(self.deputy_warnings(missing)), 1, missing)
            self.assertEqual(missing["status"], present["status"])

    def test_deputy_root_that_is_not_a_git_repo_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            shared, local = init_root(base / "shared"), init_root(base / "local")
            plain = base / "deputy"
            plain.mkdir()
            report = self.doctor(shared, local, plain)
            self.assertEqual(len(self.deputy_warnings(report)), 1, report)


class DeputyRulesTest(unittest.TestCase):
    def test_rules_init_only_deputy_seeds_what_belongs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            shared, local = init_root(base / "shared"), init_root(base / "local")
            deputy = init_root(base / "deputy")
            r = run_ledger("--root", str(shared), "--local-root", str(local),
                           "--deputy-root", str(deputy), "rules", "--init", "--only", "deputy")
            self.assertEqual(r.returncode, 0, r.stderr)
            rules = deputy / "WHAT-BELONGS.txt"
            self.assertTrue(rules.is_file())
            self.assertIn("deputy", rules.read_text(encoding="utf-8").lower())
            self.assertFalse((shared / "WHAT-BELONGS.txt").exists())
            self.assertFalse((local / "WHAT-BELONGS.txt").exists())


class DefaultOpenSetTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.shared, self.local, self.deputy = base / "shared", base / "local", base / "deputy"
        for root in (self.shared, self.local, self.deputy):
            root.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def kinds(self, only: str | None) -> list[str]:
        return [lg.kind for lg in open_ledgers(str(self.shared), str(self.local), only=only,
                                               deputy_override=str(self.deputy))]

    def test_default_open_set_excludes_the_deputy_root(self) -> None:
        self.assertEqual(self.kinds(None), ["shared", "local"])

    def test_only_deputy_opens_the_deputy_root(self) -> None:
        self.assertEqual(self.kinds("deputy"), ["deputy"])


if __name__ == "__main__":
    unittest.main()
