"""Exercise author checkpoint bookkeeping through the public executable."""
import concurrent.futures
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
COMMAND = PLUGIN / ("scripts" if (PLUGIN / "scripts").is_dir() else "bin") / "self-review"


class SelfReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.task = self.root / "task"
        self.project = self.root / "project"
        self.project.mkdir()

    def call(self, command, data=None, stage="spec", expected=0):
        argv = [str(COMMAND), command, "--task-folder", str(self.task),
                "--project-root", str(self.project), "--stage", stage, "--json"]
        if data is not None:
            argv += ["--input", "-"]
        result = subprocess.run(argv, input=json.dumps(data) if data is not None else None,
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def open(self, data=None, stage="spec"):
        return self.call("open", data if data is not None else {"candidates": [], "selections": []}, stage)

    def record(self, number, result="found", stage="spec", refs=None, expected=0):
        return self.call("pass", {"expected_pass": number, "result": result,
                                 "unresolved_refs": refs or []}, stage, expected)

    def source(self, name, mode="absorb", scope="selected phases: authoring; orchestration"):
        return {"name": name, "mode": mode, "scope": scope, "coverage": "Applies to this artifact.",
                "confirmation": {"kind": "user-message", "ref": "conversation:choice-1"}}

    def test_empty_status_is_successful_and_creates_nothing(self):
        status = self.call("status")
        self.assertFalse(status["record_exists"])
        self.assertEqual(status["checkpoints"], [])
        self.assertFalse(self.task.exists())

    def test_stages_have_separate_caps_and_closed_entries_are_immutable(self):
        self.open()
        self.record(1, refs=["caller:open"])
        before = (self.task / "self-review.json").read_bytes()
        self.record(1, expected=2)
        self.assertEqual((self.task / "self-review.json").read_bytes(), before)
        self.assertEqual(self.record(2)["outcome"], "limit-reached")
        self.assertEqual(self.open(stage="code")["passes"], 0)
        self.assertEqual(self.record(1, "clean", "code")["outcome"], "clean")
        before = (self.task / "self-review.json").read_bytes()
        self.call("configure", {"candidates": [], "selections": []}, expected=2)
        self.assertEqual((self.task / "self-review.json").read_bytes(), before)
        self.call("open", {"candidates": [], "selections": []}, expected=2)
        renewed = self.open({"candidates": [], "selections": [],
                             "renewal": {"kind": "independent-revision", "ref": "review:slate-2"}})
        self.assertEqual((renewed["visit"], renewed["passes"]), (2, 0))

    def test_clean_at_cap_and_duplicate_concurrent_calls(self):
        self.open()
        with concurrent.futures.ThreadPoolExecutor(2) as executor:
            futures = [executor.submit(subprocess.run,
                        [str(COMMAND), "pass", "--task-folder", str(self.task), "--stage", "spec",
                         "--json", "--input", "-"],
                        input=json.dumps({"expected_pass": 1, "result": "found", "unresolved_refs": []}),
                        text=True, capture_output=True, check=False) for _ in range(2)]
        results = [future.result() for future in futures]
        self.assertEqual(sorted(result.returncode for result in results), [0, 2])
        self.assertEqual(self.call("status")["passes"], 1)
        self.assertEqual(self.record(2, "clean")["outcome"], "clean")

    def test_project_union_missing_inventory_and_grouped_modes(self):
        config = self.project / ".bootgear/config"
        config.mkdir(parents=True)
        (config / "self-review.json").write_text(json.dumps({"candidates": [{"name": "alpha"}, {"name": "beta"}]}))
        self.assertEqual(self.call("open", {}, expected=2)["outcome"], "needs-candidates")
        result = self.call("open", {"candidates": [], "selections": []}, expected=2)
        self.assertEqual(result["outcome"], "needs-selection")
        self.assertEqual(result["pending"], ["alpha", "beta"])
        self.assertFalse((self.task / "self-review.json").exists())
        self.open({"candidates": [], "selections": [self.source("alpha", "invoke"), self.source("beta", "neither")]})
        self.assertEqual(len(self.call("status")["candidates"]), 2)

    def test_reconfiguration_preserves_snapshots_scope_and_budget(self):
        inventory = [{"name": "alpha", "origin": "user-request"}]
        self.open({"candidates": inventory, "selections": [self.source("alpha")]})
        self.record(1)
        changed = self.source("alpha", "invoke", "only wording (spec); no runtime checks")
        result = self.call("configure", {"candidates": inventory, "selections": [changed]})
        self.assertEqual(result["passes"], 1)
        self.assertEqual(result["selections"][0]["scope"], changed["scope"])
        old = result["pass_history"][0]["selections"][0]
        self.assertEqual(old["mode"], "absorb")
        before = (self.task / "self-review.json").read_bytes()
        changed.pop("confirmation")
        refused = self.call("configure", {"candidates": inventory, "selections": [changed]}, expected=2)
        self.assertIn("confirmation", refused["diagnostic"])
        self.assertEqual((self.task / "self-review.json").read_bytes(), before)

    def test_bad_structured_fields_group_errors_without_write(self):
        result = self.call("open", {"candidates": [{"name": "-bad", "origin": "invented"}],
                                   "selections": [self.source("unknown")], "limit": 4}, expected=2)
        for fragment in ("name", "origin", "unknown", "limit_confirmation"):
            self.assertIn(fragment, result["diagnostic"])
        self.assertFalse((self.task / "self-review.json").exists())

    def test_file_input_relative_gear_paths_and_settings(self):
        source = self.root / "request.json"
        source.write_text(json.dumps({"candidates": [], "selections": []}))
        env = dict(os.environ, GEAR_CALLER_CWD=str(self.root))
        result = subprocess.run([str(COMMAND), "open", "--task-folder", "task", "--project-root", "project",
                                 "--stage", "spec", "--input", "request.json", "--json"],
                                text=True, capture_output=True, check=False, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["task_folder"], str(self.task))
        self.assertEqual(self.call("settings")["defaults"]["limit"], 2)

    def test_unavailable_lock_reports_real_mechanism_without_record(self):
        self.task.mkdir()
        (self.task / ".self-review.lock").mkdir()
        result = self.call("open", {"candidates": [], "selections": []}, expected=3)
        self.assertEqual(result["outcome"], "unavailable")
        self.assertIn("advisory-lock", result["diagnostic"])
        self.assertFalse((self.task / "self-review.json").exists())

    def test_process_exit_releases_lock_and_existing_lockfile_is_not_ownership(self):
        self.task.mkdir()
        code = ("import fcntl,sys; lock=open(sys.argv[1], 'a+'); "
                "fcntl.flock(lock.fileno(), fcntl.LOCK_EX); "
                "print('locked', flush=True); sys.stdin.read()")
        process = subprocess.Popen(["python3", "-c", code, str(self.task / ".self-review.lock")],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        assert process.stdout is not None
        self.assertEqual(process.stdout.readline().strip(), "locked")
        process.terminate()
        process.communicate(timeout=5)
        self.assertEqual(self.open()["passes"], 0)

    def test_budget_cannot_reset_or_increase_and_renewal_needs_evidence(self):
        self.open()
        self.record(1)
        before = (self.task / "self-review.json").read_bytes()
        self.call("open", {"candidates": [], "selections": [],
                           "renewal": {"kind": "independent-revision", "ref": "review:early"}}, expected=2)
        self.call("configure", {"candidates": [], "selections": [], "limit": 3,
                                "limit_confirmation": {"kind": "user-message", "ref": "conversation:limit"}}, expected=2)
        self.assertEqual((self.task / "self-review.json").read_bytes(), before)
        self.record(2)
        before = (self.task / "self-review.json").read_bytes()
        for renewal in ({"kind": "independent-revision"}, {"ref": "review:x"}):
            self.call("open", {"candidates": [], "selections": [], "renewal": renewal}, expected=2)
            self.assertEqual((self.task / "self-review.json").read_bytes(), before)
        result = self.open({"candidates": [], "selections": [], "limit": 3,
                            "limit_confirmation": {"kind": "user-message", "ref": "conversation:limit"},
                            "renewal": {"kind": "confirmed-intent-change", "ref": "conversation:changed",
                                        "confirmation": {"kind": "user-confirmed-ledger-entry", "ref": "ledger:choice"}}})
        self.assertEqual((result["visit"], result["limit"]), (2, 3))
        self.assertEqual(result["checkpoints"][0]["passes"], 2)

    def test_project_origins_survive_union_and_config_removal(self):
        config = self.project / ".bootgear/config"
        config.mkdir(parents=True)
        project_file = config / "self-review.json"
        project_file.write_text(json.dumps({"candidates": [{"name": "alpha"}]}))
        inventory = [{"name": "alpha", "origin": "user-request"}, {"name": "beta", "origin": "host-registration"}]
        selections = [self.source("alpha"), self.source("beta")]
        selections[1]["confirmation"] = {"kind": "user-confirmed-ledger-entry", "ref": "ledger:confirmed"}
        result = self.open({"candidates": inventory, "selections": selections})
        self.assertEqual(result["candidates"][0]["origins"], ["project-config", "user-request"])
        self.record(1)
        project_file.unlink()
        before = (self.task / "self-review.json").read_bytes()
        refused = self.call("configure", {"candidates": [], "selections": []}, expected=2)
        self.assertIn("alpha", refused["diagnostic"])
        self.assertEqual((self.task / "self-review.json").read_bytes(), before)
        result = self.call("configure", {"candidates": inventory, "selections": selections})
        self.assertIn("project-config", result["candidates"][0]["origins"])
        before = (self.task / "self-review.json").read_bytes()
        selections[0]["confirmation"] = {"kind": "deputy-advice", "ref": "deputy:advice"}
        refused = self.call("configure", {"candidates": inventory, "selections": selections}, expected=2)
        self.assertIn("confirmation.kind", refused["diagnostic"])
        self.assertEqual((self.task / "self-review.json").read_bytes(), before)

    def test_pass_validation_groups_errors_and_default_output_is_prose(self):
        self.open()
        before = (self.task / "self-review.json").read_bytes()
        refused = self.call("pass", {"expected_pass": 0, "result": "unknown", "unresolved_refs": ["-bad", ""]}, expected=2)
        for field in ("expected_pass", "result", "unresolved_refs[0]", "unresolved_refs[1]"):
            self.assertIn(field, refused["diagnostic"])
        self.assertEqual((self.task / "self-review.json").read_bytes(), before)
        env = dict(os.environ)
        env.pop("BOOTGEAR_OUTPUT", None)
        result = subprocess.run([str(COMMAND), "status", "--task-folder", str(self.task)],
                                text=True, capture_output=True, check=False, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Outcome: ready", result.stdout)
        self.assertTrue(result.stdout.splitlines()[-1].startswith("Next:"))

    def test_usage_error_names_commands_example_and_next(self):
        result = subprocess.run([str(COMMAND), "open"], text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 2)
        for fragment in ("Example:", "Commands:", "Next:"):
            self.assertIn(fragment, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
