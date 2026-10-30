from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
LEDGER = PLUGIN / "scripts" / "ledger.py"
WRAPPER = PLUGIN / "scripts" / "ledger"
CODEX_HOOK = PLUGIN / "hooks" / "codex_nudge.py"
GEAR = PLUGIN.parents[1] / "cli" / "gear.py"
REPOSITORY = PLUGIN.parents[1]
sys.path.insert(0, str(PLUGIN / "scripts"))
from ledgerlib.constants import SHOW_MAX_YES_SIGS


def git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)


class CodexCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="memory-ledger-codex-"))
        self.home = self.temp / "home"
        self.caller = self.temp / "caller"
        self.shared = self.temp / "shared"
        self.local = self.temp / "local"
        self.home.mkdir()
        git_repo(self.caller)
        git_repo(self.shared)
        git_repo(self.local)
        config = self.caller / ".memory-ledger" / "config.yaml"
        config.parent.mkdir()
        config.write_text(f"memory:\n  root: {self.shared}\n  local_root: {self.local}\n")

    def env(self) -> dict[str, str]:
        return {**os.environ, "HOME": str(self.home), "BOOTGEAR_OUTPUT": "prose"}

    def run_wrapper(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in self.env().items()
               if k not in ("BOOTGEAR_OUTPUT", "BOOTGEAR_PROG")}
        return subprocess.run(
            [str(WRAPPER), *args], cwd=self.caller,
            env=env, capture_output=True, text=True, check=False,
        )

    def run_direct(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(LEDGER), *args], cwd=self.caller,
            env=self.env(), capture_output=True, text=True, check=False,
        )

    def run_gear(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(GEAR), "--root", str(REPOSITORY),
             "memory-ledger", "ledger", *args], cwd=self.caller,
            env=self.env(), capture_output=True, text=True, check=False,
        )

    def run_hook(self, hook: Path, payload: dict, *, home: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(hook)], cwd=self.caller,
            env={**self.env(), "HOME": str(home or self.home)},
            input=json.dumps(payload), capture_output=True, text=True, check=False,
        )

    def test_direct_and_gear_preserve_caller_roots(self) -> None:
        direct = self.run_direct("resolve-roots", "--json")
        gear = self.run_gear("resolve-roots", "--json")
        self.assertEqual(direct.returncode, 0, direct.stderr)
        self.assertEqual(gear.returncode, 0, gear.stderr)
        self.assertEqual(json.loads(direct.stdout), json.loads(gear.stdout))

    def test_direct_and_gear_preserve_caller_repo_and_evidence_cwd(self) -> None:
        common = (
            "--shared", "--q", "Which caller context?",
            "--anyway",
            "--claim", "The caller context reaches ledger writes.",
            "--because", "The gear child runs from its plugin root.",
            "--ref", "main", "--evidence", "pwd",
        )
        direct = self.run_direct(
            "--host", "codex", "--session-id", "caller-context-1234",
            "new", "tech/direct-context", *common,
            "--as", "codex:caller-context-1234",
        )
        gear = self.run_gear(
            "--host", "codex", "--session-id", "caller-context-1234",
            "new", "tech/gear-context", *common,
            "--as", "codex:caller-context-1234",
        )
        self.assertEqual(direct.returncode, 0, direct.stderr)
        self.assertEqual(gear.returncode, 0, gear.stderr)
        direct_entry = (self.shared / "tech" / "direct-context.md").read_text()
        gear_entry = (self.shared / "tech" / "gear-context.md").read_text()
        self.assertIn("Repo: caller", direct_entry)
        self.assertIn("Repo: caller", gear_entry)
        self.assertIn("codex:caller-context-1234", direct_entry)
        self.assertIn("codex:caller-context-1234", gear_entry)

    def test_codex_signer_keeps_exact_session_and_rejects_conflict(self) -> None:
        session = "session-full-1234"
        created = self.run_direct(
            "--host", "codex", "--session-id", session,
            "new", "tech/codex-signer", "--shared", "--q", "Which signer?",
            "--claim", "Codex keeps the complete session identity.",
            "--because", "The host session is the signer.",
            "--evidence", "pwd",
            "--as", f"codex:{session}",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        entry = (self.shared / "tech" / "codex-signer.md").read_text()
        self.assertIn(f"✓ codex:{session} ", entry)

        before = entry
        rejected = self.run_direct(
            "--host", "codex", "--session-id", session,
            "sign", "tech/codex-signer", "a1", "--as", "codex:other-session",
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("conflicts", rejected.stderr + rejected.stdout)
        self.assertEqual((self.shared / "tech" / "codex-signer.md").read_text(), before)

    def test_same_codex_session_can_correct_its_signature(self) -> None:
        session = "session-correction-1234"
        created = self.run_direct(
            "--host", "codex", "--session-id", session,
            "new", "tech/codex-correction", "--shared", "--q", "Which correction?",
            "--claim", "The first signer can correct its own vote.",
            "--because", "The exact identity proves ownership.",
            "--evidence", "pwd", "--as", f"codex:{session}",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        corrected = self.run_direct(
            "--host", "codex", "--session-id", session,
            "sign", "tech/codex-correction", "a1", "--fail", "--output", "contradiction",
            "--as", f"codex:{session}",
        )
        self.assertEqual(corrected.returncode, 0, corrected.stderr)
        self.assertIn(f"✗ codex:{session} ",
                      (self.shared / "tech" / "codex-correction.md").read_text())

    def test_show_limits_codex_signatures_like_the_claude_host(self) -> None:
        slug = "tech/codex-show-limit"
        author = "c0de0000-0000-0000-0000-000000000000"
        dissent = "c0dedead-0000-0000-0000-000000000000"
        voters = [f"c0de{n:04x}-0000-0000-0000-000000000000" for n in range(1, 8)]
        total_yes = len(voters) + 1

        def marks(stdout: str) -> tuple[list[str], list[str]]:
            lines = stdout.splitlines()
            return ([ln for ln in lines if ln.startswith("    ✓ ")],
                    [ln for ln in lines if ln.startswith("    ✗ ")])

        created = self.run_wrapper(
            "--host", "codex", "--session-id", author,
            "new", slug, "--shared", "--q", "Should show print every Codex signature?",
            "--claim", "Codex show prints every signature.",
            "--because", "Because: test. Context: none.",
            "--evidence", "true", "--as", f"codex:{author}",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        for n, session in enumerate(voters, start=1):
            if n == 2:
                failed = self.run_wrapper(
                    "--host", "codex", "--session-id", dissent,
                    "sign", slug, "a1", "--fail", "--output", "boom",
                    "--as", f"codex:{dissent}",
                )
                self.assertEqual(failed.returncode, 0, failed.stderr)
            signed = self.run_wrapper(
                "--host", "codex", "--session-id", session,
                "sign", slug, "a1", "--as", f"codex:{session}",
            )
            self.assertEqual(signed.returncode, 0, signed.stderr)

        capped = self.run_wrapper("--host", "codex", "--session-id", author, "show", slug)
        self.assertEqual(capped.returncode, 0, capped.stderr)
        yes, no = marks(capped.stdout)
        self.assertEqual(len(yes), SHOW_MAX_YES_SIGS, capped.stdout)
        self.assertEqual(len(no), 1, capped.stdout)
        self.assertIn(voters[-1].split("-")[0], yes[0])
        for hidden in [author, *voters][:total_yes - SHOW_MAX_YES_SIGS]:
            self.assertFalse(any(hidden.split("-")[0] in ln for ln in yes), capped.stdout)
        self.assertIn(f"… {total_yes - SHOW_MAX_YES_SIGS} older ✓ not shown", capped.stdout)
        self.assertIn(f"{total_yes}✓/1✗", capped.stdout)

        everything = self.run_wrapper("--host", "codex", "--session-id", author,
                                      "show", slug, "--all-sigs")
        self.assertEqual(everything.returncode, 0, everything.stderr)
        yes, no = marks(everything.stdout)
        self.assertEqual(len(yes), total_yes, everything.stdout)
        self.assertEqual(len(no), 1, everything.stdout)
        self.assertIn(voters[-1].split("-")[0], yes[0])
        self.assertNotIn("not shown", everything.stdout)
        self.assertIn(f"{total_yes}✓/1✗", everything.stdout)
        data = self.run_wrapper("--host", "codex", "--session-id", author, "show", slug, "--data")
        self.assertEqual(data.returncode, 0, data.stderr)
        self.assertEqual(json.loads(data.stdout)["slug"], slug)

    def test_codex_footer_counts_only_valid_yes_signatures(self) -> None:
        slug = "tech/codex-voided-tail"
        author = "c0de1000-0000-0000-0000-000000000000"
        voters = [f"c0de{n:04x}-0000-0000-0000-000000000000" for n in range(0x1001, 0x1008)]
        fresh = "c0de2000-0000-0000-0000-000000000000"
        created = self.run_wrapper(
            "--host", "codex", "--session-id", author,
            "new", slug, "--shared", "--q", "Does the Codex footer skip voided check-marks?",
            "--claim", "The Codex footer skips voided check-marks.",
            "--because", "Because: test. Context: none.",
            "--evidence", "true", "--as", f"codex:{author}",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        for session in voters:
            signed = self.run_wrapper(
                "--host", "codex", "--session-id", session,
                "sign", slug, "a1", "--as", f"codex:{session}",
            )
            self.assertEqual(signed.returncode, 0, signed.stderr)
        path = self.shared / "tech" / "codex-voided-tail.md"
        body = path.read_text(encoding="utf-8")
        path.write_text(body.replace("The Codex footer skips voided check-marks.",
                                     "The Codex footer skips voided check-marks only."),
                        encoding="utf-8")
        resigned = self.run_wrapper(
            "--host", "codex", "--session-id", fresh,
            "sign", slug, "a1", "--as", f"codex:{fresh}",
        )
        self.assertEqual(resigned.returncode, 0, resigned.stderr)
        shown = self.run_wrapper("--host", "codex", "--session-id", author, "show", slug)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("1✓/0✗", shown.stdout, shown.stdout)
        self.assertIn(f"{len(voters) + 1} voided by an edit", shown.stdout, shown.stdout)
        self.assertNotIn("not shown", shown.stdout)

    def test_doctor_json_distinguishes_unconfigured_and_configured(self) -> None:
        absent_home = self.temp / "absent-home"
        absent_home.mkdir()
        result = subprocess.run(
            [sys.executable, str(LEDGER), "--root", str(self.temp / "missing-shared"),
             "--local-root", str(self.temp / "missing-local"), "doctor", "--json"],
            cwd=self.temp, env={**os.environ, "HOME": str(absent_home)},
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "unconfigured")

        configured = self.run_direct("doctor", "--json")
        self.assertEqual(configured.returncode, 0, configured.stderr)
        self.assertEqual(json.loads(configured.stdout)["status"], "configured")

        partial = subprocess.run(
            [sys.executable, str(LEDGER), "--root", str(self.temp / "missing-shared"),
             "--local-root", str(self.local), "doctor", "--json"],
            cwd=self.temp, env={**os.environ, "HOME": str(absent_home)},
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(partial.returncode, 1, partial.stderr)
        self.assertEqual(json.loads(partial.stdout)["status"], "broken")

        malformed_local = self.temp / "malformed-local"
        malformed_local.write_text("not a ledger repository")
        malformed = subprocess.run(
            [sys.executable, str(LEDGER), "--root", str(self.shared),
             "--local-root", str(malformed_local), "doctor", "--json"],
            cwd=self.temp, env={**os.environ, "HOME": str(absent_home)},
            capture_output=True, text=True, check=False,
        )
        malformed_data = json.loads(malformed.stdout)
        self.assertEqual(malformed.returncode, 1, malformed.stderr)
        self.assertEqual(malformed_data["status"], "broken")
        self.assertTrue(any("local ledger" in warning for warning in malformed_data["warnings"]))

        malformed_shared = self.temp / "malformed-shared"
        malformed_shared.write_text("not a ledger repository")
        shared_malformed = subprocess.run(
            [sys.executable, str(LEDGER), "--root", str(malformed_shared),
             "--local-root", str(self.temp / "another-missing-local"), "doctor", "--json"],
            cwd=self.temp, env={**os.environ, "HOME": str(absent_home)},
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(shared_malformed.returncode, 1, shared_malformed.stderr)
        self.assertEqual(json.loads(shared_malformed.stdout)["status"], "broken")

        warnings = json.loads(self.run_direct("doctor", "--json").stdout)["warnings"]
        self.assertTrue(warnings)

    def test_codex_hook_translates_nudge_cooldown_and_reset(self) -> None:
        payload = {
            "session_id": "hook-session-full-1234",
            "cwd": str(self.caller),
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": "x.py"},
        }
        first = self.run_hook(CODEX_HOOK, payload)
        self.assertEqual(first.returncode, 0, first.stderr)
        first_output = json.loads(first.stdout)
        self.assertIn("additionalContext", first_output["hookSpecificOutput"])

        second = self.run_hook(CODEX_HOOK, {**payload, "tool_name": "Bash"})
        self.assertEqual(second.stdout, "")

        used = self.run_hook(CODEX_HOOK, {**payload, "tool_name": "Bash",
                                          "tool_input": {"command": "ledger.py show x"}})
        self.assertEqual(used.stdout, "")
        marker = (self.home / ".memory-ledger" / ".nudge-state"
                  / "hook-session-full-1234.last")
        self.assertEqual(json.loads(marker.read_text())["event"], "ledger-used")

        after_reset = self.run_hook(CODEX_HOOK, {**payload, "tool_name": "Read"})
        self.assertIn("additionalContext", json.loads(after_reset.stdout)["hookSpecificOutput"])

    def test_codex_hook_counts_the_wrapper_as_ledger_use(self) -> None:
        payload = {
            "session_id": "hook-session-wrapper-1234",
            "cwd": str(self.caller),
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": "x.py"},
        }
        self.assertIn("additionalContext",
                      json.loads(self.run_hook(CODEX_HOOK, payload).stdout)["hookSpecificOutput"])
        used = self.run_hook(CODEX_HOOK, {**payload, "tool_name": "Bash",
                                          "tool_input": {"command": f"{PLUGIN}/scripts/ledger show x"}})
        self.assertEqual(used.stdout, "")
        marker = (self.home / ".memory-ledger" / ".nudge-state"
                  / "hook-session-wrapper-1234.last")
        self.assertEqual(json.loads(marker.read_text())["event"], "ledger-used")

    def test_wrapper_is_executable_and_prints_prose_on_a_pipe(self) -> None:
        self.assertTrue(os.access(WRAPPER, os.X_OK))
        doctor = self.run_wrapper("doctor")
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        self.assertIn("failure(s)", doctor.stdout)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(doctor.stdout)

    def test_wrapper_json_flag_prints_legacy_doctor_object(self) -> None:
        doctor = self.run_wrapper("doctor", "--json")
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        self.assertEqual(json.loads(doctor.stdout)["status"], "configured")

    def test_wrapper_next_names_the_wrapper(self) -> None:
        session = "session-wrapper-1234"
        created = self.run_wrapper(
            "--host", "codex", "--session-id", session,
            "new", "tech/wrapper-next", "--local", "--q", "Which next program?",
            "--claim", "The wrapper names itself in next.",
            "--because", "BOOTGEAR_PROG is the wrapper path.",
            "--evidence", "pwd", "--as", f"codex:{session}",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(created.stdout.splitlines()[-1], f"next: {WRAPPER} save")

    def test_codex_hook_reports_unconfigured_without_nudging(self) -> None:
        bare_home = self.temp / "bare-home"
        bare_caller = self.temp / "bare-caller"
        bare_home.mkdir()
        bare_caller.mkdir()
        payload = {
            "session_id": "hook-session-full-1234",
            "cwd": str(bare_caller),
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": {},
        }
        result = subprocess.run(
            [sys.executable, str(CODEX_HOOK)], cwd=bare_caller,
            env={**self.env(), "HOME": str(bare_home)}, input=json.dumps(payload),
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"systemMessage": "memory-ledger: unconfigured"})

    def test_concurrent_codex_hooks_emit_at_most_one_nudge(self) -> None:
        payload = {
            "session_id": "hook-session-concurrent-1234",
            "cwd": str(self.caller),
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": {},
        }
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.run_hook(CODEX_HOOK, payload), range(4)))
        outputs = [result.stdout for result in results if result.stdout.strip()]
        self.assertLessEqual(sum("additionalContext" in output for output in outputs), 1)

    def test_codex_package_selects_one_explicit_hook_runtime(self) -> None:
        manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["hooks"], "./hooks/codex-hooks.json")
        hooks = json.loads((PLUGIN / "hooks" / "codex-hooks.json").read_text())
        command = hooks["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
        self.assertIn("${PLUGIN_ROOT}", command)
        marketplace = json.loads((REPOSITORY / ".agents" / "plugins" / "marketplace.json").read_text())
        entries = [plugin for plugin in marketplace["plugins"] if plugin["name"] == "memory-ledger"]
        self.assertEqual(entries, [{
            "name": "memory-ledger",
            "source": "./plugins/memory-ledger",
            "description": "Codex skill and hook adapter for the canonical append-only memory ledger.",
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        }])
        self.assertFalse((REPOSITORY / "codex-plugins" / "memory-ledger").exists())


if __name__ == "__main__":
    unittest.main()
