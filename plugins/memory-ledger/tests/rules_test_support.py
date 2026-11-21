"""The per-ledger rule file: `rules`, `save`, `doctor`, `resolve`, `new` and the shipped defaults.

Every run is a subprocess against temp ledger roots; nothing here touches a real ledger.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# `new` signs with this Claude id when the host did not set one, also in a Codex shell.
# Set before any printed command is built: the host adds `--host claude` to it.
os.environ.setdefault("CLAUDE_CODE_SESSION_ID", "rules-test-session")
os.environ["BOOTGEAR_HOST"] = "claude"

from bootgear_cli.clikit import gear_command

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "scripts"
LEDGER = SCRIPTS / "ledger.py"
GEAR = PLUGIN.parents[1] / "plugins" / "cli" / "bin" / "gear"
GEAR_COMMAND = shlex.join([str(GEAR), "--host", "codex", "memory-ledger", "ledger"])
DIRECT_COMMAND = gear_command("memory-ledger", "ledger")
RULES_DIR = PLUGIN / "rules"
RULES_FILE = "WHAT-BELONGS.txt"
CACHE_FILE = ".ledger-cache.json"

SHARED_HEADINGS = (
    "What belongs in the shared ledger",
    "An entry",
    "Belongs here",
    "A check must run on any teammate's machine",
    "Does not belong here",
    "Dating and change",
    "This team's own rules",
)
LOCAL_HEADINGS = (
    "What belongs in the local ledger",
    "Belongs here",
    "Moving entries",
    "Keep out",
    "This team's own rules",
)

sys.path.insert(0, str(SCRIPTS))
import ledger as ledger_cli
from bootgear_cli import clikit


def _git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            text=True, check=True)
    return result.stdout


def _default_text(kind: str) -> str:
    return (RULES_DIR / f"{kind}.txt").read_text(encoding="utf-8")


class TempLedgerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="memory-ledger-rules-"))
        self.home = self.temp / "home"
        self.home.mkdir()
        self.shared = self.temp / "shared"
        self.local = self.temp / "local"
        _git_repo(self.shared)
        _git_repo(self.local)

    def env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items()
               if k not in (clikit.ENV_MODE, clikit.ENV_PROG, clikit.ENV_CALLER_CWD)}
        env.update(HOME=str(self.home), LEDGER_ROOT=str(self.shared),
                   LEDGER_LOCAL_ROOT=str(self.local),
                   GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.invalid",
                   GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.invalid")
        return env

    def run_ledger(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(LEDGER), *args], cwd=self.temp,
                              env=self.env(), capture_output=True, text=True, check=False)

    def ok(self, *args: str) -> str:
        result = self.run_ledger(*args)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result.stdout

    def new_entry(self, kind: str, slug: str = "tech/seeded",
                  question: str = "Which colour is the sky?") -> subprocess.CompletedProcess[str]:
        return self.run_ledger(
            "new", slug, f"--{kind}", "--q", question, "--claim", "The sky is blue.",
            "--because", "Look up.", "--evidence", "true", "--as", "author-a")

    def rules_file(self, kind: str) -> Path:
        return (self.shared if kind == "shared" else self.local) / RULES_FILE

__all__ = ['clikit', 'ledger_cli']
