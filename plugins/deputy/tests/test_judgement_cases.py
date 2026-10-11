"""The judge's eval cases: fixed past decisions and the outcome the ask skill must return.

This file checks that the case set is well formed and covers each required case. It does not
run the judge. Running the cases through the `ask` skill is a manual step, because the judge
is an LLM and its answers are not reproducible by code (design C10).
"""
from __future__ import annotations

import unittest

OUTCOMES = {"answered", "escalate", "not-applicable"}

CASES = [
    {
        "name": "covered question with three agreeing decisions",
        "question": "Should new scripts run with uv?",
        "past": [("decisions/use-uv", "agree"), ("decisions/uv-again", "agree"),
                 ("decisions/uv-third", "agree")],
        "expect": "answered",
    },
    {
        "name": "only two agreeing decisions",
        "question": "Should new scripts run with uv?",
        "past": [("decisions/use-uv", "agree"), ("decisions/uv-again", "agree")],
        "expect": "escalate",
    },
    {
        "name": "three agreeing and one conflicting",
        "question": "Should new scripts run with uv?",
        "past": [("decisions/use-uv", "agree"), ("decisions/uv-again", "agree"),
                 ("decisions/uv-third", "agree"), ("decisions/pip-once", "conflict")],
        "expect": "escalate",
    },
    {
        "name": "unrelated question with no citation",
        "question": "Which database should the reporting job use?",
        "past": [("decisions/use-uv", "unrelated")],
        "expect": "escalate",
    },
    {
        "name": "only citation is unrelated",
        "question": "Which database should the reporting job use?",
        "past": [("decisions/use-uv", "unrelated")],
        "expect": "escalate",
    },
    {
        "name": "covering assertion below the threshold",
        "question": "Should production use uv?",
        "past": [("assertions/uv-everywhere", "covers")],
        "stakes": "below",
        "expect": "answered",
    },
    {
        "name": "covering assertion at or above the threshold",
        "question": "Should production use uv?",
        "past": [("assertions/uv-everywhere", "covers")],
        "stakes": "at-or-above",
        "expect": "escalate",
    },
    {
        "name": "citation outside the candidate list",
        "question": "Should new scripts run with uv?",
        "past": [("decisions/not-listed", "agree")],
        "candidates_exclude": ["decisions/not-listed"],
        "expect": "escalate",
    },
    {
        "name": "hard-gate action",
        "question": "May I push the production migration now?",
        "past": [],
        "hard_gate": True,
        "expect": "not-applicable",
    },
]

REQUIRED = {
    "covered question with three agreeing decisions",
    "unrelated question with no citation",
    "only citation is unrelated",
    "covering assertion at or above the threshold",
    "citation outside the candidate list",
    "hard-gate action",
}


class JudgementCaseSetTest(unittest.TestCase):
    def test_every_case_has_a_question_and_a_known_outcome(self) -> None:
        for case in CASES:
            with self.subTest(case=case["name"]):
                self.assertTrue(case["question"])
                self.assertIn(case["expect"], OUTCOMES)

    def test_the_required_cases_are_present(self) -> None:
        names = {case["name"] for case in CASES}
        self.assertTrue(REQUIRED <= names, REQUIRED - names)

    def test_no_case_name_is_repeated(self) -> None:
        names = [case["name"] for case in CASES]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
