"""The Codex engine bundle carries copies of the Claude converge and review
sources; these tests fail when a copy drifts from its source."""

import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_DIR.parents[1]
CLAUDE_ENGINE = REPO_ROOT / "plugins" / "engine"
CLAUDE_CONVERGE = REPO_ROOT / "plugins" / "converge"
CLAUDE_REVIEW = REPO_ROOT / "plugins" / "review" / "skills" / "review"
CODEX_SKILLS = PLUGIN_DIR / "skills"
HOST_MECHANICS = "## Host mechanics\n"

# hooks/state_nudge_reminder.py and tests/test_state_nudge_hook.py are not
# byte-identical copies: they carry legitimate host adaptations (paths,
# wording). Each pair below is (exact Claude text, exact Codex text); every
# Claude-side block must occur exactly once in the source so a stale entry
# fails loudly instead of silently matching nothing.
HOOK_ADAPTATIONS: list[tuple[str, str]] = [
    ("Claude Code hooks support", "Codex hooks support"),
    ('task_bin = plugin_dir / "bin" / "task"', 'task_bin = plugin_dir / "scripts" / "task"'),
]

TEST_FILE_ADAPTATIONS: list[tuple[str, str]] = [
    (
        '"""Tests for plugins/engine/hooks/state_nudge_reminder.py.',
        '"""Tests for hooks/state_nudge_reminder.py.',
    ),
    ("bin/task, then manipulates", "scripts/task, then manipulates"),
    ('TASK_BIN = PLUGIN_DIR / "bin" / "task"', 'TASK_BIN = PLUGIN_DIR / "scripts" / "task"'),
]


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def _body_above_host_mechanics(path: Path) -> str:
    text = path.read_text()
    if not text.startswith("---\n"):
        raise AssertionError(f"{path}: no front matter")
    body = text[text.index("\n---\n", 4) + len("\n---\n"):]
    if HOST_MECHANICS not in body:
        raise AssertionError(f"{path}: no {HOST_MECHANICS.strip()!r} section")
    return body[: body.index(HOST_MECHANICS)]


class BundleDriftTest(unittest.TestCase):
    def assertSameTree(self, source: Path, copy: Path):
        expected, actual = _files(source), _files(copy)
        self.assertTrue(expected, f"{source} is empty or missing")
        self.assertEqual(sorted(actual), sorted(expected), f"file set of {copy}")
        changed = [name for name in expected if actual[name] != expected[name]]
        self.assertEqual(changed, [], f"bytes differ from {source}")

    def assertSameBytes(self, source: Path, copy: Path):
        self.assertEqual(copy.read_bytes(), source.read_bytes(), f"{copy} differs from {source}")

    def _adapted_text(self, source_text: str, adaptations: list[tuple[str, str]], source: Path) -> str:
        for claude_block, codex_block in adaptations:
            count = source_text.count(claude_block)
            self.assertEqual(
                count, 1,
                f"{source}: expected exactly one occurrence of {claude_block!r}, found {count} "
                "(a stale allowlist entry, or new unreviewed drift near it)",
            )
            source_text = source_text.replace(claude_block, codex_block)
        return source_text

    def assertAdaptedMatch(self, source: Path, copy: Path, adaptations: list[tuple[str, str]]):
        expected = self._adapted_text(source.read_text(), adaptations, source)
        self.assertEqual(copy.read_text(), expected, f"{copy} has unreviewed drift from {source}")

    def test_converge_package_matches_claude_source(self):
        self.assertSameTree(
            CLAUDE_CONVERGE / "src" / "converge", PLUGIN_DIR / "src" / "converge"
        )

    def test_converge_skill_body_matches_above_host_mechanics(self):
        self.assertEqual(
            _body_above_host_mechanics(CODEX_SKILLS / "converge" / "SKILL.md"),
            _body_above_host_mechanics(CLAUDE_CONVERGE / "skills" / "converge" / "SKILL.md"),
        )

    def test_converge_reference_matches(self):
        self.assertSameBytes(
            CLAUDE_CONVERGE / "skills" / "converge" / "reference.md",
            CODEX_SKILLS / "converge" / "reference.md",
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

    def test_review_reference_and_references_match(self):
        self.assertSameBytes(
            CLAUDE_REVIEW / "reference.md", CODEX_SKILLS / "review" / "reference.md"
        )
        self.assertSameTree(
            CLAUDE_REVIEW / "references", CODEX_SKILLS / "review" / "references"
        )

    def test_state_nudge_hook_matches_claude_source(self):
        self.assertAdaptedMatch(
            CLAUDE_ENGINE / "hooks" / "state_nudge_reminder.py",
            PLUGIN_DIR / "hooks" / "state_nudge_reminder.py",
            HOOK_ADAPTATIONS,
        )

    def test_state_nudge_hook_test_matches_claude_source(self):
        self.assertAdaptedMatch(
            CLAUDE_ENGINE / "tests" / "test_state_nudge_hook.py",
            PLUGIN_DIR / "tests" / "test_state_nudge_hook.py",
            TEST_FILE_ADAPTATIONS,
        )

    def _assert_catches_unlisted_mutation(
        self, source: Path, copy: Path, adaptations: list[tuple[str, str]], needle: str
    ):
        # Mutate a line the allowlist does NOT cover, in a real temp copy of
        # the Codex file, and confirm assertAdaptedMatch itself catches it --
        # not a hand-rolled comparison, the actual method under test.
        original = copy.read_text()
        self.assertIn(needle, original, f"fixture assumption broken: {needle!r} not in {copy}")
        mutated = original.replace(needle, f"{needle}  # mutated for test", 1)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(mutated)
            mutated_copy = Path(f.name)
        try:
            with self.assertRaises(
                AssertionError, msg="positive control is broken: assertAdaptedMatch did not "
                "notice the mutation"
            ):
                self.assertAdaptedMatch(source, mutated_copy, adaptations)
        finally:
            mutated_copy.unlink()

    def test_state_nudge_hook_allowlist_catches_unlisted_drift(self):
        self._assert_catches_unlisted_mutation(
            CLAUDE_ENGINE / "hooks" / "state_nudge_reminder.py",
            PLUGIN_DIR / "hooks" / "state_nudge_reminder.py",
            HOOK_ADAPTATIONS,
            "def main() -> None:",
        )

    def test_state_nudge_hook_test_allowlist_catches_unlisted_drift(self):
        self._assert_catches_unlisted_mutation(
            CLAUDE_ENGINE / "tests" / "test_state_nudge_hook.py",
            PLUGIN_DIR / "tests" / "test_state_nudge_hook.py",
            TEST_FILE_ADAPTATIONS,
            "import unittest",
        )

    def _assert_catches_claude_side_stale_entry(
        self, source: Path, copy: Path, adaptations: list[tuple[str, str]], claude_block: str
    ):
        # Mutate the CLAUDE source's own allowlisted claude_block in a real
        # temp copy of the source, proving the count==1 stale-entry guard in
        # _adapted_text fails closed on a Claude-side edit too, not only on a
        # Codex-copy mismatch.
        original = source.read_text()
        occurrences = original.count(claude_block)
        self.assertEqual(
            occurrences, 1,
            f"fixture assumption broken: {claude_block!r} does not occur exactly once in {source}",
        )
        mutated = original.replace(claude_block, claude_block + " mutated", 1)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(mutated)
            mutated_source = Path(f.name)
        try:
            with self.assertRaises(
                AssertionError, msg="positive control is broken: a Claude-side edit to an "
                "allowlisted block did not trip the count==1 stale-entry guard"
            ):
                self.assertAdaptedMatch(mutated_source, copy, adaptations)
        finally:
            mutated_source.unlink()

    def test_state_nudge_hook_allowlist_catches_claude_side_stale_entry(self):
        self._assert_catches_claude_side_stale_entry(
            CLAUDE_ENGINE / "hooks" / "state_nudge_reminder.py",
            PLUGIN_DIR / "hooks" / "state_nudge_reminder.py",
            HOOK_ADAPTATIONS,
            "Claude Code hooks support",
        )

    def test_state_nudge_hook_test_allowlist_catches_claude_side_stale_entry(self):
        self._assert_catches_claude_side_stale_entry(
            CLAUDE_ENGINE / "tests" / "test_state_nudge_hook.py",
            PLUGIN_DIR / "tests" / "test_state_nudge_hook.py",
            TEST_FILE_ADAPTATIONS,
            "bin/task, then manipulates",
        )

    def _assert_catches_boundary_mutation(
        self,
        source: Path,
        copy: Path,
        adaptations: list[tuple[str, str]],
        codex_block: str,
        *,
        where: str,
    ):
        # Mutate the Codex copy immediately before or after an allowlisted
        # block's exact span -- not inside it -- proving the comparator
        # fails closed on drift adjacent to a tolerated block, not just
        # anywhere in the file.
        original = copy.read_text()
        index = original.find(codex_block)
        self.assertGreaterEqual(
            index, 0, f"fixture assumption broken: {codex_block!r} not found in {copy}"
        )
        if where == "before":
            mutated = original[:index] + "X" + original[index:]
        elif where == "after":
            end = index + len(codex_block)
            mutated = original[:end] + "X" + original[end:]
        else:
            raise ValueError(where)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(mutated)
            mutated_copy = Path(f.name)
        try:
            with self.assertRaises(
                AssertionError, msg=f"positive control is broken: a mutation immediately "
                f"{where} an allowlisted block's exact span was not caught"
            ):
                self.assertAdaptedMatch(source, mutated_copy, adaptations)
        finally:
            mutated_copy.unlink()

    def test_state_nudge_hook_catches_mutation_just_before_allowlisted_block(self):
        self._assert_catches_boundary_mutation(
            CLAUDE_ENGINE / "hooks" / "state_nudge_reminder.py",
            PLUGIN_DIR / "hooks" / "state_nudge_reminder.py",
            HOOK_ADAPTATIONS,
            "Codex hooks support",
            where="before",
        )

    def test_state_nudge_hook_catches_mutation_just_after_allowlisted_block(self):
        self._assert_catches_boundary_mutation(
            CLAUDE_ENGINE / "hooks" / "state_nudge_reminder.py",
            PLUGIN_DIR / "hooks" / "state_nudge_reminder.py",
            HOOK_ADAPTATIONS,
            "Codex hooks support",
            where="after",
        )


if __name__ == "__main__":
    unittest.main()
