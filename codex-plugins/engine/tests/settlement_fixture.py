"""A settlement that `task session init` and `task session validate` accept.

Tests import `valid_settlement` and supply only the state machine they need.
The text has no `session_dir:` line: `init` adds it.
"""
import textwrap

FIELDS = """\
principles: none
request_assessment: fixture assessment
source_of_truth:
  scope: fixture scope
debate_threshold: fixture reversibility rule
debate_round_cap: 1
convergence_policy: unanimous
consented_stop_allowed: true
debate_party_config: {}
debate_roster: [main-agent, independent-reviewer]
spec_skill: spec
test_skill: test
review_skill: review
review_fix_mode: accepted_only
autonomy:
  no_further_questions: true
  permitted_mutations: [run tests]
"""


def valid_settlement(machine: str, *, approach: str = "smoke test",
                     succeeded: str = "smoke test passes", failed: str = "never",
                     extra: str = "") -> str:
    """The settlement text for `machine`; `extra` is raw text placed before the fields."""
    return (
        "task_type: ticket-to-pr\n"
        f"approach: {approach}\n"
        f"{extra}"
        f"{FIELDS}"
        f"goal:\n  succeeded: {succeeded}\n  failed: {failed}\n"
        "state_machine: |\n"
        f"{textwrap.indent(machine, '  ')}"
    )
