"""The Codex engine bundle carries byte-identical copies of Claude-side code;
these tests fail when a copy drifts from its source."""

import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_DIR.parents[1]
CLAUDE_ENGINE = REPO_ROOT / "plugins" / "engine"
CLAUDE_CONVERGE = REPO_ROOT / "plugins" / "converge"


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


class BundleDriftTest(unittest.TestCase):
    def assertSameTree(self, source: Path, copy: Path):
        expected, actual = _files(source), _files(copy)
        self.assertTrue(expected, f"{source} is empty or missing")
        self.assertEqual(sorted(actual), sorted(expected), f"file set of {copy}")
        changed = [name for name in expected if actual[name] != expected[name]]
        self.assertEqual(changed, [], f"bytes differ from {source}")

    def assertSameBytes(self, source: Path, copy: Path):
        self.assertEqual(copy.read_bytes(), source.read_bytes(), f"{copy} differs from {source}")

    def test_converge_package_matches_claude_source(self):
        self.assertSameTree(
            CLAUDE_CONVERGE / "src" / "converge", PLUGIN_DIR / "src" / "converge"
        )

    def test_clikit_copies_match_engine_source(self):
        # Each plugin ships its own copy; none imports another plugin's.
        source = REPO_ROOT / "plugins" / "engine" / "src" / "engine" / "clikit.py"
        for copy in (
            PLUGIN_DIR / "src" / "engine" / "clikit.py",
            CLAUDE_CONVERGE / "src" / "converge" / "clikit.py",
            REPO_ROOT / "plugins" / "memory-ledger" / "scripts" / "ledgerlib" / "clikit.py",
        ):
            self.assertSameBytes(source, copy)

    def test_seats_copies_match_engine_source(self):
        # Settlement validation and converge init check seats with one rule set.
        source = CLAUDE_ENGINE / "src" / "engine" / "seats.py"
        for copy in (
            PLUGIN_DIR / "src" / "engine" / "seats.py",
            CLAUDE_CONVERGE / "src" / "converge" / "seats.py",
        ):
            self.assertSameBytes(source, copy)

    def test_host_adapter_core_matches_claude_source(self):
        for name in ("host_adapter.py", "host_contracts.py", "policy.py"):
            self.assertSameBytes(
                CLAUDE_ENGINE / "src" / "engine" / name,
                PLUGIN_DIR / "src" / "engine" / name,
            )


if __name__ == "__main__":
    unittest.main()
