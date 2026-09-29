"""Tests for plugins/engine/hooks/state_nudge_reminder.py.

Drives the hook as a subprocess against a real scratch ledger built with
bin/task, then manipulates the hook's own marker file directly to force the
elapsed-time and history conditions each test needs, rather than sleeping.
"""
import errno
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_DIR = Path(__file__).resolve().parents[1]
TASK_BIN = PLUGIN_DIR / "bin" / "task"
HOOK = PLUGIN_DIR / "hooks" / "state_nudge_reminder.py"

_spec = importlib.util.spec_from_file_location("state_nudge_reminder", HOOK)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"could not load {HOOK}")
state_nudge_reminder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(state_nudge_reminder)

SETTLEMENT = """\
task_type: ticket-to-pr
approach: smoke test
principles: none
source_of_truth:
  scope: ticket
debate_threshold: any
debate_round_cap: 10
convergence_policy: unanimous
consented_stop_allowed: true
debate_roster: [main-agent, independent-reviewer, adversarial-reviewer]
debate_party_config: {{}}
spec_skill: spec
test_skill: test
review_skill: review
autonomy:
  no_further_questions: true
  permitted_mutations: [edit files]
goal:
  succeeded: smoke test passes
  failed: never
state_machine: |
  name: smoke
  nodes:
    clarify:
      next: [impl]
    impl:
      next: [fix, succeeded]
    fix:
      next: [impl]
    succeeded:
      terminal: true
    failed:
      terminal: true
session_dir: {session_dir}
"""


class StateNudgeHookTest(unittest.TestCase):
    def setUp(self):
        self.session_dir = Path(tempfile.mkdtemp(prefix="state-nudge-hook-test-"))
        self.addCleanup(shutil.rmtree, self.session_dir, ignore_errors=True)
        settlement_file = self.session_dir / "settlement.txt"
        settlement_file.write_text(SETTLEMENT.format(session_dir=self.session_dir))
        self.run_id = "test-run"
        subprocess.run(
            [str(TASK_BIN), "session", "init", self.run_id,
             "--settlement-file", str(settlement_file), "--dir", str(self.session_dir)],
            capture_output=True, text=True, check=True,
        )
        self.marker_path = self.session_dir / f".{self.run_id}.state_nudge_state"
        self.home = self.session_dir / "home"
        self.home.mkdir()

    def _hook_env(self, home: Path | None = None) -> dict:
        env = os.environ.copy()
        # Keep uv's real cache: the hook's `task` subprocess runs `uv run`.
        env.setdefault("UV_CACHE_DIR", str(Path.home() / ".cache" / "uv"))
        env["HOME"] = str(home or self.home)
        return env

    def _run_hook(self, cwd: str | None = None, home: Path | None = None,
                  extra: dict | None = None) -> dict:
        payload = {"session_id": self.run_id, "cwd": cwd or str(self.session_dir),
                   **(extra or {})}
        result = subprocess.run(
            ["python3", str(HOOK)],
            input=json.dumps(payload),
            capture_output=True, text=True,
            env=self._hook_env(home),
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout.strip():
            return {}
        return json.loads(result.stdout)

    def _force_stale(self):
        """Backdate the marker so the hook treats last activity as stale,
        without waiting 5 real minutes."""
        marker = json.loads(self.marker_path.read_text()) if self.marker_path.exists() else {}
        marker["last_checked_at"] = 0.0
        self.marker_path.write_text(json.dumps(marker))

    def test_no_nudge_when_fresh(self):
        self._setup_home_ledger()
        out = self._run_hook(cwd=str(self.session_dir))
        self.assertEqual(out, {})

    def test_home_ledger_found_when_cwd_session_dir_holds_other_runs(self):
        project = self.session_dir / "project"
        project_session = project / ".bootgear" / "session"
        project_session.mkdir(parents=True)
        (project_session / "other-run.md").write_text(
            (self.session_dir / f"{self.run_id}.md").read_text()
        )
        home_ledger, home_marker = self._setup_home_ledger()
        old_ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))
        self._backdate_started(home_ledger, old_ts)

        out = self._run_hook(cwd=str(project))
        self.assertIn("hookSpecificOutput", out)
        self.assertIn("hasn't recorded a", out["hookSpecificOutput"]["additionalContext"])
        self.assertTrue(home_marker.exists())

    def test_cwd_ledger_is_not_a_run_location(self):
        cwd_session_dir = self.session_dir / "project" / ".bootgear" / "session"
        cwd_session_dir.mkdir(parents=True)
        cwd_ledger = cwd_session_dir / f"{self.run_id}.md"
        cwd_ledger.write_text((self.session_dir / f"{self.run_id}.md").read_text())
        old_ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))
        self._backdate_started(cwd_ledger, old_ts)

        out = self._run_hook(cwd=str(self.session_dir / "project"))
        self.assertEqual(out, {})
        self.assertFalse((cwd_session_dir / f".{self.run_id}.state_nudge_state").exists())

    def _setup_home_ledger(self):
        home_session_dir = self.home / ".bootgear" / "session"
        home_session_dir.mkdir(parents=True, exist_ok=True)
        ledger_src = self.session_dir / f"{self.run_id}.md"
        (home_session_dir / f"{self.run_id}.md").write_text(ledger_src.read_text())
        return (home_session_dir / f"{self.run_id}.md",
                home_session_dir / f".{self.run_id}.state_nudge_state")

    def _backdate_started(self, ledger_path: Path, old_ts: str) -> None:
        text = re.sub(r"(?m)^started: .*$", f"started: {old_ts}",
                       ledger_path.read_text())
        ledger_path.write_text(text)

    def _backdate_transitions(self, ledger_path: Path, old_ts: str) -> None:
        text = ledger_path.read_text()
        text = re.sub(r"(?m)^(- \d{4}-\d{2}-\d{2} \d{2}:\d{2}) (\S+ -> \S+ )",
                       lambda m: f"- {old_ts} {m.group(2)}", text)
        ledger_path.write_text(text)

    def test_nudges_once_stale_and_records_history(self):
        ledger_path, marker_path = self._setup_home_ledger()
        self.marker_path = marker_path

        old_ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))
        self._backdate_started(ledger_path, old_ts)

        out = self._run_hook(cwd=str(self.session_dir))
        self.assertIn("hookSpecificOutput", out)
        self.assertIn("hasn't recorded a", out["hookSpecificOutput"]["additionalContext"])

        marker = json.loads(marker_path.read_text())
        self.assertEqual(len(marker["nudges"]), 1)
        self.assertEqual(marker["nudges"][0]["node"], "clarify")
        self.assertEqual(marker["nudges"][0]["transition_index"], 0)
        self.assertFalse(marker["escalated_for_identity"])

    def test_unbroken_stall_escalates_once_then_silent(self):
        """A genuine stall (same identity, no transition) must escalate
        exactly once after the repeat interval, then go silent. A debounce
        gate that blocks any second nudge with an unchanged activity epoch
        would make this case unreachable."""
        ledger_path, marker_path = self._setup_home_ledger()

        old_ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))
        self._backdate_started(ledger_path, old_ts)

        first = self._run_hook(cwd=str(self.session_dir))
        self.assertIn("hookSpecificOutput", first)
        self.assertNotIn("already flagged", first["hookSpecificOutput"]["additionalContext"])

        # Still the same identity, only past the recheck window, and just
        # inside a hardcoded 10-minute repeat interval (identity_first_nudged_at
        # backdated to 10 real minutes ago, not left at its real just-set
        # value). Hardcoded rather than derived from
        # `_ESCALATE_AFTER_SECONDS` itself: an expectation derived from the
        # same constant can never catch a regression to that constant (a
        # backdate of `_ESCALATE_AFTER_SECONDS - 60` would go negative if
        # the constant dropped to 1 second, and any negative elapsed time
        # is still "less than" a 1-second interval). 10 minutes is comfortably below
        # the real 15-minute interval and comfortably above a broken
        # near-zero one, so this pins the interval's actual configured
        # value, not just "not literally instant."
        marker = json.loads(marker_path.read_text())
        marker["last_checked_at"] = 0.0
        marker["identity_first_nudged_at"] = time.time() - 10 * 60
        marker_path.write_text(json.dumps(marker))
        quiet = self._run_hook(cwd=str(self.session_dir))
        self.assertEqual(quiet, {})

        # Past the repeat interval: the one escalation fires.
        marker = json.loads(marker_path.read_text())
        marker["last_checked_at"] = 0.0
        marker["identity_first_nudged_at"] = 0.0
        marker_path.write_text(json.dumps(marker))
        second = self._run_hook(cwd=str(self.session_dir))
        self.assertIn("hookSpecificOutput", second)
        self.assertIn("already flagged", second["hookSpecificOutput"]["additionalContext"])

        marker = json.loads(marker_path.read_text())
        self.assertEqual(len(marker["nudges"]), 2)
        self.assertTrue(marker["escalated_for_identity"])

        # Same identity, past recheck window again: silence.
        marker["last_checked_at"] = 0.0
        marker_path.write_text(json.dumps(marker))
        third = self._run_hook(cwd=str(self.session_dir))
        self.assertEqual(third, {})

    def test_transition_resets_to_base_message(self):
        ledger_path, marker_path = self._setup_home_ledger()

        old_ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))
        self._backdate_started(ledger_path, old_ts)

        self._run_hook(cwd=str(self.session_dir))  # first nudge: clarify

        subprocess.run(
            [str(TASK_BIN), "state", "transition", self.run_id,
             "--to", "impl", "--reason", "moved on", "--dir", str(self.session_dir)],
            capture_output=True, text=True, check=True,
        )
        ledger_path.write_text((self.session_dir / f"{self.run_id}.md").read_text())

        marker = json.loads(marker_path.read_text())
        marker["last_checked_at"] = 0.0
        marker_path.write_text(json.dumps(marker))

        # New node (impl) just transitioned into, but re-backdate so it also
        # reads as stale immediately for this test.
        self._backdate_transitions(ledger_path, old_ts)

        out = self._run_hook(cwd=str(self.session_dir))
        self.assertIn("hookSpecificOutput", out)
        self.assertNotIn("already flagged", out["hookSpecificOutput"]["additionalContext"])

        marker = json.loads(marker_path.read_text())
        self.assertEqual(marker["nudges"][-1]["node"], "impl")
        self.assertEqual(marker["nudges"][-1]["transition_index"], 1)

    def test_same_minute_transition_pair_is_new_identity(self):
        """Two distinct transitions landing in the same clock minute, on the
        SAME node name, must not be mistaken for 'nothing changed'; node/epoch-only
        identity is insufficient. Driven
        through the real hook subprocess with a marker pre-set to the
        earlier identity, so this actually exercises main()'s identity
        comparison rather than only the node name. The node name is kept the
        same between checks, so the test fails if transition_index is
        deleted from the identity."""
        ledger_path, marker_path = self._setup_home_ledger()

        old_ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))
        self._backdate_started(ledger_path, old_ts)

        # Ledger state: current node "impl", reached via three transitions
        # (clarify -> impl -> fix -> impl), all timestamped in the same
        # backdated minute -- so a node-only OR epoch-only identity would
        # consider this "the same thing" as a marker pre-set to only the
        # first two of those transitions having happened.
        for dest, reason in (("impl", "start"), ("fix", "diagnosing"), ("impl", "back to impl")):
            subprocess.run(
                [str(TASK_BIN), "state", "transition", self.run_id,
                 "--to", dest, "--reason", reason, "--dir", str(self.session_dir)],
                capture_output=True, text=True, check=True,
            )
        ledger_path.write_text((self.session_dir / f"{self.run_id}.md").read_text())
        self._backdate_transitions(ledger_path, old_ts)

        # Pre-set the marker as if node "impl" was already nudged about at
        # the SAME epoch but at transition_index=1 (i.e. as of just the
        # first clarify -> impl transition) -- same node, same minute,
        # earlier ordinal. This is the identity a node/epoch-only design
        # cannot distinguish from the real, later state (node "impl", same
        # epoch, transition_index=3, after the impl -> fix -> impl cycle).
        marker_path.write_text(json.dumps({
            "last_checked_at": 0.0,
            "last_nudged_identity": ["impl", state_nudge_reminder._parse_minute_ts(old_ts), 1],
            "identity_first_nudged_at": 0.0,
            "escalated_for_identity": False,
            "nudges": [],
        }))

        out = self._run_hook(cwd=str(self.session_dir))
        self.assertIn("hookSpecificOutput", out)
        self.assertNotIn("already flagged", out["hookSpecificOutput"]["additionalContext"])
        marker = json.loads(marker_path.read_text())
        self.assertEqual(marker["last_nudged_identity"], ["impl", state_nudge_reminder._parse_minute_ts(old_ts), 3])
        self.assertEqual(marker["nudges"][-1]["transition_index"], 3)

    def test_revisit_after_cycle_does_not_falsely_escalate(self):
        """test-code -> fix -> test-code: revisiting a node name through a
        real transition cycle must read as a fresh (base-message) nudge, not
        an escalation, which a node-only identity would produce. Driven through the real hook subprocess with a marker pre-set
        to the earlier same-node identity, so this actually exercises
        main()'s escalation decision, so it catches a regression to node-only
        escalation."""
        ledger_path, marker_path = self._setup_home_ledger()

        old_ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))
        self._backdate_started(ledger_path, old_ts)

        # Real cycle: clarify -> impl -> fix -> impl. Ends back on node
        # "impl" (same name as the earlier identity below) but at a later
        # transition_index.
        for dest, reason in (("impl", "start"), ("fix", "bug found"), ("impl", "fixed")):
            subprocess.run(
                [str(TASK_BIN), "state", "transition", self.run_id,
                 "--to", dest, "--reason", reason, "--dir", str(self.session_dir)],
                capture_output=True, text=True, check=True,
            )
        ledger_path.write_text((self.session_dir / f"{self.run_id}.md").read_text())
        self._backdate_transitions(ledger_path, old_ts)

        # Pre-set the marker as though node "impl" was already nudged AND
        # escalated at an earlier point in the cycle (transition_index=1,
        # i.e. right after the first clarify -> impl). A node-only
        # escalation design would see "same node as last time" here and
        # escalate again; the real, later identity is transition_index=3.
        marker_path.write_text(json.dumps({
            "last_checked_at": 0.0,
            "last_nudged_identity": ["impl", state_nudge_reminder._parse_minute_ts(old_ts), 1],
            "identity_first_nudged_at": 0.0,
            "escalated_for_identity": True,
            "nudges": [{"at": 0.0, "node": "impl", "activity": state_nudge_reminder._parse_minute_ts(old_ts), "transition_index": 1}],
        }))

        out = self._run_hook(cwd=str(self.session_dir))
        self.assertIn("hookSpecificOutput", out)
        self.assertNotIn("already flagged", out["hookSpecificOutput"]["additionalContext"])
        marker = json.loads(marker_path.read_text())
        self.assertEqual(marker["last_nudged_identity"], ["impl", state_nudge_reminder._parse_minute_ts(old_ts), 3])
        self.assertFalse(marker["escalated_for_identity"])

    def test_legacy_marker_takes_base_path_once_then_escalates_normally(self):
        """A legacy marker (no last_nudged_identity) is legacy for exactly
        one check, not permanently exempt from escalation (the very call that takes
        the base-only path also records last_nudged_identity, so 15 minutes
        later on the same stall it escalates like any other identity)."""
        ledger_path, marker_path = self._setup_home_ledger()

        old_ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))
        self._backdate_started(ledger_path, old_ts)

        # Legacy marker shape: has last_checked_at but predates
        # last_nudged_identity / escalated_for_identity entirely.
        marker_path.write_text(json.dumps({"last_checked_at": 0.0}))

        first = self._run_hook(cwd=str(self.session_dir))
        self.assertIn("hookSpecificOutput", first)
        self.assertNotIn("already flagged", first["hookSpecificOutput"]["additionalContext"])

        marker = json.loads(marker_path.read_text())
        self.assertIn("last_nudged_identity", marker)
        self.assertFalse(marker["escalated_for_identity"])

        # Same identity, past both the recheck window and the escalation
        # interval: escalates normally, exactly like a marker that always
        # had last_nudged_identity.
        marker["last_checked_at"] = 0.0
        marker["identity_first_nudged_at"] = 0.0
        marker_path.write_text(json.dumps(marker))
        second = self._run_hook(cwd=str(self.session_dir))
        self.assertIn("hookSpecificOutput", second)
        self.assertIn("already flagged", second["hookSpecificOutput"]["additionalContext"])

    def test_subagent_tool_call_is_ignored(self):
        """A subagent's tool call carries the parent's session_id plus an
        agent_id. The nudge is for the session driving the run, so a
        subagent call must neither nudge nor touch the shared marker."""
        ledger_path, marker_path = self._setup_home_ledger()
        old_ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))
        self._backdate_started(ledger_path, old_ts)

        out = self._run_hook(cwd=str(self.session_dir), extra={"agent_id": "sub-1"})
        self.assertEqual(out, {})
        self.assertFalse(marker_path.exists())

    def test_marker_missing_first_nudged_at_records_it_then_escalates(self):
        """A marker naming the current identity but lacking
        identity_first_nudged_at must record it, not stay silent forever."""
        ledger_path, marker_path = self._setup_home_ledger()
        old_ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))
        self._backdate_started(ledger_path, old_ts)
        marker_path.write_text(json.dumps({
            "last_checked_at": 0.0,
            "last_nudged_identity": ["clarify", state_nudge_reminder._parse_minute_ts(old_ts), 0],
            "escalated_for_identity": False,
        }))

        quiet = self._run_hook(cwd=str(self.session_dir))
        self.assertEqual(quiet, {})
        marker = json.loads(marker_path.read_text())
        self.assertAlmostEqual(marker["identity_first_nudged_at"], time.time(), delta=60)

        marker["last_checked_at"] = 0.0
        marker["identity_first_nudged_at"] = 0.0
        marker_path.write_text(json.dumps(marker))
        second = self._run_hook(cwd=str(self.session_dir))
        self.assertIn("already flagged", second["hookSpecificOutput"]["additionalContext"])

    def test_unwritable_session_dir_still_nudges(self):
        """A lock file that cannot be created is not contention: the hook
        runs unlocked rather than silently skipping the nudge."""
        ledger_path, marker_path = self._setup_home_ledger()
        old_ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))
        self._backdate_started(ledger_path, old_ts)
        session_dir = ledger_path.parent
        session_dir.chmod(0o555)
        self.addCleanup(session_dir.chmod, 0o755)

        out = self._run_hook(cwd=str(self.session_dir))
        self.assertIn("hasn't recorded a", out["hookSpecificOutput"]["additionalContext"])
        self.assertFalse(Path(str(marker_path) + ".lock").exists())

    def test_non_dict_marker_is_treated_as_empty(self):
        ledger_path, marker_path = self._setup_home_ledger()
        old_ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))
        self._backdate_started(ledger_path, old_ts)
        marker_path.write_text("[]")

        out = self._run_hook(cwd=str(self.session_dir))
        self.assertIn("hasn't recorded a", out["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(len(json.loads(marker_path.read_text())["nudges"]), 1)

    def test_non_contention_flock_error_proceeds_unlocked(self):
        """Only contention means another hook is checking; any other flock
        error (e.g. ENOLCK on NFS without a lock daemon) proceeds unlocked."""
        marker_path = self.session_dir / "marker"

        def failing_flock(fd, op):
            raise OSError(errno.ENOLCK, "no locks available")

        with mock.patch.object(state_nudge_reminder.fcntl, "flock", failing_flock):
            self.assertEqual(state_nudge_reminder._try_lock(marker_path), (True, None))

    def test_concurrent_hook_runs_nudge_once(self):
        """Parallel tool calls start their PostToolUse hooks concurrently.
        However many overlap, a stale run gets exactly one nudge and one
        history entry."""
        ledger_path, marker_path = self._setup_home_ledger()
        old_ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))
        self._backdate_started(ledger_path, old_ts)
        payload = json.dumps({"session_id": self.run_id, "cwd": str(self.session_dir)})

        procs = [subprocess.Popen(["python3", str(HOOK)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, env=self._hook_env())
                 for _ in range(6)]
        # The hook blocks reading stdin until EOF: let every interpreter
        # finish starting, then release them together so their marker
        # reads overlap instead of being staggered by startup time.
        pipes = []
        for p in procs:
            assert p.stdin and p.stdout and p.stderr
            pipes.append((p.stdin, p.stdout, p.stderr))
        for stdin, _, _ in pipes:
            stdin.write(payload)
            stdin.flush()
        time.sleep(1.0)
        for stdin, _, _ in pipes:
            stdin.close()
        outputs = [(stdout.read(), stderr.read()) for _, stdout, stderr in pipes]
        for p in procs:
            p.wait()

        for p, (_, err) in zip(procs, outputs):
            self.assertEqual(p.returncode, 0, err)
        nudged = [out for out, _ in outputs if out.strip()]
        self.assertEqual(len(nudged), 1, nudged)
        self.assertEqual(len(json.loads(marker_path.read_text())["nudges"]), 1)

    def test_history_capped_at_50(self):
        """50 pre-seeded entries, each with a distinguishable `at` value, so
        the new entry appended by this call must evict the OLDEST (index 0,
        `at`: 0) and keep the newest 49 plus the one just appended -- not
        just any 50 entries. Distinct values matter: a wrong-end eviction,
        keeping the oldest 50 and dropping the new entry, would otherwise
        produce an indistinguishable-looking marker."""
        ledger_path, marker_path = self._setup_home_ledger()
        marker = {
            "last_checked_at": 0.0,
            "last_nudged_identity": ["other", 0.0, 0],
            "nudges": [{"at": i, "node": "clarify", "activity": i, "transition_index": 0}
                       for i in range(50)],
        }
        marker_path.write_text(json.dumps(marker))

        old_ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))
        self._backdate_started(ledger_path, old_ts)

        self._run_hook(cwd=str(self.session_dir))

        marker = json.loads(marker_path.read_text())
        self.assertEqual(len(marker["nudges"]), 50)
        # Oldest seeded entry (at=0) must be evicted; entries 1..49 survive,
        # and the newly appended entry (identity ["clarify", ...] but a
        # distinct, real `at` timestamp from `time.time()`) is now last.
        seeded_ats = [n["at"] for n in marker["nudges"][:-1]]
        self.assertEqual(seeded_ats, list(range(1, 50)))
        self.assertNotIn(marker["nudges"][-1]["at"], range(50))
        self.assertEqual(marker["nudges"][-1]["node"], "clarify")


if __name__ == "__main__":
    unittest.main()
