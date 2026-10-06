"""`unportable_paths` and the shared-write gate built on it: which paths in an `Evidence:` line count as personal.

Pure functions, no subprocess.
"""
from __future__ import annotations

import sys
import unittest

from test_rules import SCRIPTS

sys.path.insert(0, str(SCRIPTS))

from ledgerlib.audit import unportable_paths  # noqa: E402
from ledgerlib.gates import portability_problem  # noqa: E402

FOLDER_CHECK = 'test -d "${LEDGER_ROOT:-$HOME/.memory-ledger/shared}/tech/browser"'


class ExpansionTailTests(unittest.TestCase):
    def test_a_folder_after_a_braced_expansion_is_not_a_path(self) -> None:
        self.assertEqual(unportable_paths(FOLDER_CHECK), [])
        self.assertIsNone(portability_problem([FOLDER_CHECK], kind="shared"))

    def test_a_home_expansion_followed_by_a_path_is_accepted(self) -> None:
        self.assertEqual(unportable_paths("ls ${HOME}/Code/x/"), [])
        self.assertEqual(unportable_paths("ls $HOME/Code/x/"), [])

    def test_a_quote_between_the_brace_and_the_path_stays_flagged(self) -> None:
        self.assertEqual(unportable_paths('ls "${LEDGER_ROOT}"/tech/browser/'),
                         ["/tech/browser/"])


class PersonalPathPins(unittest.TestCase):
    """What must stay flagged or accepted whatever the expansion rule does."""

    def test_home_and_scratchpad_paths_are_flagged(self) -> None:
        scratchpad = "/private/tmp/claude-" + "501/x/y/"
        self.assertEqual(unportable_paths("ls /Users/someone/y/"), ["/Users/someone/y/"])
        self.assertEqual(unportable_paths("ls ~/work/x/"), ["~/work/x/"])
        self.assertEqual(unportable_paths(f"ls {scratchpad}"), [scratchpad])

    def test_tool_cache_and_system_paths_are_accepted(self) -> None:
        self.assertEqual(unportable_paths("ls ~/.gradle/x/"), [])
        self.assertEqual(unportable_paths("ls /usr/local/bin/"), [])


if __name__ == "__main__":
    unittest.main()
