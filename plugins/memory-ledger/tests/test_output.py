"""Output mode, refusals and `next` for ledger.py (clikit wiring).

Every run is a subprocess against temp ledger roots, so stdout is a real pipe;
prose is the default unless a test requests JSON explicitly.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "scripts"
LEDGER = SCRIPTS / "ledger.py"

sys.path.insert(0, str(SCRIPTS))
import ledger as ledger_cli
from ledgerlib import clikit


def _git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)


class LedgerOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="memory-ledger-output-"))
        self.home = self.temp / "home"
        self.home.mkdir()
        self.shared = self.temp / "shared"
        self.local = self.temp / "local"
        _git_repo(self.shared)
        _git_repo(self.local)

    def env(self, **extra: str) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items()
               if k not in (clikit.ENV_MODE, clikit.ENV_PROG, clikit.ENV_CALLER_CWD)}
        env.update(HOME=str(self.home), LEDGER_ROOT=str(self.shared),
                   LEDGER_LOCAL_ROOT=str(self.local))
        env.update(extra)
        return env

    def run_pipe(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(LEDGER), *args], cwd=self.temp,
                              env=self.env(**env), capture_output=True, text=True,
                              check=False)

    def run_file(self, *args: str) -> tuple[int, str, str]:
        out = self.temp / "stdout.txt"
        with out.open("w") as handle:
            result = subprocess.run([sys.executable, str(LEDGER), *args], cwd=self.temp,
                                    env=self.env(), stdout=handle, stderr=subprocess.PIPE,
                                    text=True, check=False)
        return result.returncode, out.read_text(), result.stderr

    def seed(self, slug: str = "tech/seeded", question: str = "Which colour is the sky?",
             *extra: str) -> None:
        result = self.run_pipe(
            "new", slug, "--local", "--q", question, "--claim", "The sky is blue.",
            "--because", "Look up.", "--evidence", "true", "--as", "author-a", *extra)
        self.assertEqual(result.returncode, 0, result.stderr)

    # -- pipe default -------------------------------------------------------

    def test_list_with_json_prints_lines_object(self) -> None:
        self.seed()
        result = self.run_pipe("list", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(set(data), {"lines"})
        self.assertTrue(any("tech/seeded" in line for line in data["lines"]))

    def test_list_to_a_file_prints_prose(self) -> None:
        self.seed()
        code, out, err = self.run_file("list")
        self.assertEqual(code, 0, err)
        self.assertIn("tech/seeded", out)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(out)

    def test_sign_lifts_save_next(self) -> None:
        self.seed()
        result = self.run_pipe("sign", "tech/seeded", "a1", "--as", "verifier-b", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["next"], "ledger.py save")
        self.assertFalse(any(line.startswith("next:") for line in data["lines"]))

    def test_write_prose_ends_with_save_next(self) -> None:
        code, out, err = self.run_file(
            "new", "tech/prose", "--local", "--q", "Is prose next printed?",
            "--claim", "It is.", "--because", "Printed by the CLI.", "--evidence", "true",
            "--as", "author-a")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines()[-1], "next: ledger.py save")

    def test_resolve_exact_names_show_next(self) -> None:
        self.seed()
        result = self.run_pipe("resolve", "tech/seeded", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["next"], "ledger.py show tech/seeded")
        self.assertTrue(any(line.startswith("EXACT") for line in data["lines"]))

    def test_resolve_exact_follows_a_cached_redirect(self) -> None:
        self.seed()
        self.seed("tech/moved", "Where did the moved entry go?")
        path = self.local / "tech" / "moved.md"
        lines = path.read_text().splitlines()
        path.write_text("\n".join([*lines[:2], "USE: tech/seeded", *lines[2:]]) + "\n")
        self.assertEqual(self.run_pipe("list").returncode, 0)   # re-index into the cache
        result = self.run_pipe("resolve", "tech/moved", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["next"], "ledger.py show tech/seeded")
        self.assertIn("USE-redirect from tech/moved", " ".join(data["lines"]))

    def test_resolve_fuzzy_has_no_next(self) -> None:
        self.seed()
        result = self.run_pipe("resolve", "sky colour question", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("next", json.loads(result.stdout))

    def test_list_without_flag_on_a_pipe_prints_prose(self) -> None:
        self.seed()
        result = self.run_pipe("list")
        self.assertIn("tech/seeded", result.stdout)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(result.stdout)

    # -- own_json commands --------------------------------------------------

    def test_doctor_json_keeps_legacy_shape_and_exit_codes(self) -> None:
        configured = self.run_pipe("doctor", "--json")
        self.assertEqual(configured.returncode, 0, configured.stderr)
        self.assertEqual(json.loads(configured.stdout)["status"], "configured")
        missing = self.run_pipe("--root", str(self.temp / "no-shared"),
                                "--local-root", str(self.temp / "no-local"),
                                "doctor", "--json")
        self.assertEqual(missing.returncode, 3, missing.stderr)
        self.assertEqual(json.loads(missing.stdout)["status"], "unconfigured")

    def test_doctor_without_flag_on_a_pipe_prints_prose(self) -> None:
        missing = self.run_pipe("--root", str(self.temp / "no-shared"),
                                "--local-root", str(self.temp / "no-local"), "doctor")
        self.assertEqual(missing.returncode, 1, missing.stderr)
        self.assertIn("FAIL  shared ledger", missing.stdout)

    # -- refusals -----------------------------------------------------------

    def test_already_asked_new_refusal_carries_existing_list(self) -> None:
        self.seed()
        result = self.run_pipe(
            "new", "tech/again", "--local", "--q", "Which colour is the sky?",
            "--claim", "Blue.", "--because", "Again.", "--evidence", "true",
            "--as", "author-a", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        error = json.loads(result.stderr)["error"]
        self.assertEqual(error["command"], "new")
        self.assertTrue(any(line.startswith("EXISTING") for line in error["lines"]))
        self.assertTrue(any("tech/seeded" in line for line in error["lines"]))
        kinds = [p["kind"] for p in error["problems"]]
        self.assertEqual(kinds, ["restates an existing question"])

    def test_new_without_ledger_flag_prints_example(self) -> None:
        args = ("new", "tech/x", "--q", "q?", "--claim", "c.", "--because", "b.",
                "--evidence", "true")
        piped = self.run_pipe(*args, "--json")
        self.assertEqual(piped.returncode, 1)
        error = json.loads(piped.stderr)["error"]
        self.assertIn("say which ledger", error["message"])
        self.assertEqual(error["example"], "ledger.py " + ledger_cli.EXAMPLES["new"])
        self.assertIn("resolve", error["examples"])

        code, _, err = self.run_file(*args)
        self.assertEqual(code, 1)
        lines = err.splitlines()
        self.assertTrue(lines[0].startswith("say which ledger"))
        self.assertIn(f"example: ledger.py {ledger_cli.EXAMPLES['new']}", lines)
        self.assertTrue(any(line.startswith("commands: ") for line in lines))
        self.assertIn(f"  ledger.py {ledger_cli.EXAMPLES['show']}", lines)

    def test_argparse_error_prints_example_and_exits_2(self) -> None:
        result = self.run_pipe("show", "--prose")
        self.assertEqual(result.returncode, 2)
        lines = result.stderr.splitlines()
        self.assertTrue(lines[0].startswith("ledger.py show: error:"), result.stderr)
        self.assertIn(f"example: ledger.py {ledger_cli.EXAMPLES['show']}", lines)
        self.assertNotIn("usage:", result.stderr)

    def test_new_collects_every_problem_before_running_evidence(self) -> None:
        marker = self.temp / "ran"
        claim = " ".join(["word"] * 60)
        result = self.run_pipe(
            "new", "tech/bad", "--shared", "--q", "Does a bad new refuse once?",
            "--claim", claim, "--because", "b.",
            "--evidence", f"touch {marker}; ls /Users/someone/x", "--as", "author-a",
            "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(marker.exists(), "an Evidence line ran before the refusal")
        self.assertNotIn("ran, exit", result.stdout)
        self.assertIn("claim too long (1):", result.stderr)
        self.assertIn("hardcoded personal path (1):", result.stderr)
        self.assertIn("claim is 60 words", result.stderr)
        self.assertIn("/Users/someone/x", result.stderr)
        self.assertFalse((self.shared / "tech" / "bad.md").exists())

    # -- catalog drift ------------------------------------------------------

    def test_examples_cover_every_leaf_and_parse(self) -> None:
        parser = ledger_cli.build_parser()
        self.assertEqual(set(ledger_cli.EXAMPLES), set(clikit.leaf_commands(parser)))
        for command, example in ledger_cli.EXAMPLES.items():
            args, extra = parser.parse_known_args(shlex.split(example))
            self.assertEqual(extra, [], example)
            self.assertEqual(args.cmd, command)
        self.assertEqual(ledger_cli.CATALOG.capture, frozenset(ledger_cli.EXAMPLES))
        self.assertTrue(set(ledger_cli.CATALOG.frequent) <= set(ledger_cli.EXAMPLES))
        self.assertTrue(ledger_cli.SAVE_NEXT <= set(ledger_cli.EXAMPLES))


if __name__ == "__main__":
    unittest.main()
