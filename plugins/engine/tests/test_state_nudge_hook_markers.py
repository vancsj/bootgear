import errno
import json
import subprocess
import time
from unittest import mock

from state_nudge_hook_test_support import StateNudgeHookTestCase, state_nudge_reminder


class StateNudgeHookTest(StateNudgeHookTestCase):
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

    def test_unwritable_session_dir_reports_policy_error_without_marker_write(self):
        """The native adapter reports a policy error before it writes a marker."""
        ledger_path, marker_path = self._setup_home_ledger()
        old_ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))
        self._backdate_started(ledger_path, old_ts)
        session_dir = ledger_path.parent
        session_dir.chmod(0o555)
        self.addCleanup(session_dir.chmod, 0o755)

        out = self._run_hook(cwd=str(self.session_dir))
        self.assertEqual(out, {})
        self.assertEqual(self.last_hook_result.returncode, 0)
        self.assertIn("policy_apply_error", self.last_hook_result.stderr)
        self.assertFalse(marker_path.exists())

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
        payload = json.dumps(self._hook_input(str(self.session_dir)))

        procs = [subprocess.Popen(self._hook_argv(), stdin=subprocess.PIPE,
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
