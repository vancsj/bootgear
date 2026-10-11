"""Text presence at the ask-first call sites: the ask, the hard-gate sentence and the fallback marker.

This checks that the instructions are written. It does not check that a model follows them;
the routing behaviour is recorded as an open item, not tested (F013).
"""
from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ASKING = [
    "plugins/engine/skills/clarify/SKILL.md",
    "plugins/engine/skills/execute/SKILL.md",
    "plugins/engine/skills/resolve/SKILL.md",
    "plugins/engine/skills/debate/SKILL.md",
    "plugins/review/skills/review/SKILL.md",
    "codex-plugins/engine/skills/clarify/SKILL.md",
    "codex-plugins/engine/skills/execute/SKILL.md",
    "codex-plugins/engine/skills/resolve/SKILL.md",
    "codex-plugins/engine/skills/debate/SKILL.md",
]
HANDBACK_ONLY = ["plugins/converge/skills/converge/SKILL.md"]
HARD_GATE = ("production change, outward send, irreversible action, goal sign-off, "
             "or permitted mutations are never sent to")
MARKER = "no-deputy:not-installed"


class CallSiteTextTest(unittest.TestCase):
    def test_every_asking_call_site_calls_the_ask_skill(self) -> None:
        for rel in ASKING:
            with self.subTest(file=rel):
                self.assertIn("deputy:ask", (REPO / rel).read_text(encoding="utf-8"))

    def test_every_asking_call_site_states_the_hard_gate_rule(self) -> None:
        for rel in ASKING + HANDBACK_ONLY:
            with self.subTest(file=rel):
                self.assertIn(HARD_GATE, (REPO / rel).read_text(encoding="utf-8").lower())

    def test_every_asking_call_site_has_the_fallback_marker(self) -> None:
        for rel in ASKING:
            with self.subTest(file=rel):
                self.assertIn(MARKER, (REPO / rel).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
