import json
import subprocess
import time
import unittest

from gear_commands import TASK as TASK_COMMAND
from gear_commands import display
from state_nudge_hook_test_support import StateNudgeHookTestCase, state_nudge_reminder


class StateNudgeHookTest(StateNudgeHookTestCase):
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

    def test_nudges_once_stale_and_records_history(self):
        ledger_path, marker_path = self._setup_home_ledger()
        self.marker_path = marker_path

        old_ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))
        self._backdate_started(ledger_path, old_ts)

        out = self._run_hook(cwd=str(self.session_dir))
        self.assertIn("hookSpecificOutput", out)
        context = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("hasn't recorded a", context)
        self.assertIn(f"`{display('engine', 'task')} state transition`", context)

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
        self.assertIn("hookSpecificOutput", second, self.last_hook_result.stderr)
        context = second["hookSpecificOutput"]["additionalContext"]
        self.assertIn("already flagged", context)
        self.assertIn(f"`{display('engine', 'task')} state transition`", context)

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
            [*TASK_COMMAND, "state", "transition", self.run_id,
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
                [*TASK_COMMAND, "state", "transition", self.run_id,
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
                [*TASK_COMMAND, "state", "transition", self.run_id,
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
        self.assertIn("hookSpecificOutput", second, self.last_hook_result.stderr)
        self.assertIn("already flagged", second["hookSpecificOutput"]["additionalContext"])


if __name__ == "__main__":
    unittest.main()
