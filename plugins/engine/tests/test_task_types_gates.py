import json

import yaml
from gear_commands import HOST
from task_types_test_support import (
    CUT_EVIDENCE,
    EVERY_CLAIM_RULE,
    GATE_CHECK,
    OVERRIDES,
    PRODUCT_RULE,
    REFERENCES,
    REPO_ROOT,
    RERUN_ONLY,
    TRIAGE_MACHINES,
    TRIAGE_PROFILES,
    UNREACHABLE_RULE,
    Scratch,
    _load_yaml,
    _rule,
)


class GateChecks(Scratch):
    def test_check_ix_cutoff_profiles_match_d3_and_converge_init_exits_0(self):
        profiles = {
            REPO_ROOT / "plugins" / "engine" / "references" / "cutoff-product.yaml":
                [PRODUCT_RULE, EVERY_CLAIM_RULE],
            OVERRIDES / "cutoff-one-user.yaml": [PRODUCT_RULE, UNREACHABLE_RULE, EVERY_CLAIM_RULE],
        }
        for index, (path, attack_rules) in enumerate(profiles.items()):
            with self.subTest(path=str(path)):
                lens = _load_yaml(path)["cutoff"]["lenses"]["default"]
                self.assertEqual([_rule(rule) for rule in lens["attack_if"]], attack_rules)
                self.assertEqual([_rule(rule) for rule in lens["report_if"]], [PRODUCT_RULE])
                result = self._slate(f"d3-{index}", defaults=path)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_triage_profiles_open_no_gap_hunt(self):
        for profile, path in TRIAGE_PROFILES.items():
            with self.subTest(profile=profile):
                covered = self._filed_and_covered(f"gap-{profile}", path)
                self.assertNotIn("gap hunt", covered.stdout)
                status = self._converge("status", f"gap-{profile}", "--dir", str(self.ledgers))
                self.assertEqual(status.returncode, 0, status.stderr)
                self.assertNotIn("gap hunt", status.stdout)
                self.assertIn("next: escalate: finder escalate F001", status.stdout)
                work = self._converge("work", f"gap-{profile}", "--dir", str(self.ledgers),
                                      "--as", "r2", "--role-host", HOST, "--json")
                self.assertEqual(work.returncode, 0, work.stderr)
                self.assertFalse(any(item["action"] == "gap-hunt"
                                     for item in json.loads(work.stdout)["items"]))
        # Positive control: the same profile without its `steps` opens the gap hunt.
        without_steps = _load_yaml(TRIAGE_PROFILES["product"])
        without_steps.pop("steps", None)
        control = self.tmp / "cutoff-no-steps.yaml"
        control.write_text(yaml.safe_dump(without_steps))
        self._filed_and_covered("gap-on", control)
        work = self._converge("work", "gap-on", "--dir", str(self.ledgers),
                              "--as", "r2", "--role-host", HOST, "--json")
        self.assertEqual(work.returncode, 0, work.stderr)
        self.assertTrue(any(item["action"] == "gap-hunt"
                            for item in json.loads(work.stdout)["items"]))

    def test_triage_profiles_attack_a_claim_rated_outside_the_product_rule(self):
        ratings = (("cosmetic", "normal"), ("clarity", "unreachable"), ("cosmetic", "unreachable"))
        for profile, path in TRIAGE_PROFILES.items():
            for impact, reach in ratings:
                slate = f"attack-{profile}-{impact}-{reach}"
                with self.subTest(profile=profile, impact=impact, reach=reach):
                    self._filed_and_covered(slate, path)
                    escalated = self._converge("escalate", slate, "--dir", str(self.ledgers),
                                               "--as", "finder", "--claim", "F001")
                    self.assertEqual(escalated.returncode, 0, escalated.stderr)
                    cut = self._converge("cut", slate, "--dir", str(self.ledgers), "--as", "cutter",
                                         "--claim", "F001", "--when", "before", "--round", "1",
                                         "--impact", impact, "--size", "one", "--reach", reach,
                                         *CUT_EVIDENCE)
                    self.assertEqual(cut.returncode, 0, cut.stderr)
                    status = self._converge("status", slate, "--dir", str(self.ledgers), "--json")
                    self.assertEqual(status.returncode, 0, status.stderr)
                    (claim,) = json.loads(status.stdout)["claims"]
                    self.assertEqual(claim["rating"]["impact"], impact)
                    self.assertEqual(claim["rating"]["reach"], reach)
                    self.assertEqual(claim["status"], "survived")

    def test_check_x_triage_review_alone_runs_the_gate_on_its_exit(self):
        for label, path in TRIAGE_MACHINES.items():
            with self.subTest(machine=label):
                nodes = _load_yaml(path)["nodes"]
                gate_next = "disposition" if label == "override" else "succeeded"
                self.assertEqual(nodes["triage-review"]["next"],
                                 ["triage", "triage-debate", gate_next])
                self.assertEqual(nodes["triage-review"]["reminder"]["exit_checks"],
                                 {gate_next: {"argv": GATE_CHECK, "on_refuse": "triage"}})
                checked = [name for name, node in nodes.items()
                           if {"leave_check", "exit_checks"} & set(node.get("reminder") or {})]
                self.assertEqual(checked, ["triage-review"])

    def test_triage_review_exits_to_triage_and_triage_debate_run_no_gate(self):
        for label, path in TRIAGE_MACHINES.items():
            for dest in ("triage", "triage-debate"):
                run_id = f"{label}-{dest}"
                with self.subTest(machine=label, dest=dest):
                    ledger = self._triage_run(run_id, path, "triage-review")
                    moved = self._move(run_id, dest)
                    self.assertEqual(moved.returncode, 0, moved.stderr)
                    self.assertIn(f"current: {dest}\n", ledger.read_text())
                    log = ledger.read_text().splitlines()
                    entry = next(line for line in reversed(log) if line.startswith("- "))
                    self.assertTrue(entry.endswith(f"triage-review -> {dest} (to {dest})"), entry)

    def test_triage_review_refuses_a_failing_report_back_to_triage(self):
        task_layer = self.tmp / "rerun-only.yaml"
        task_layer.write_text(RERUN_ONLY)
        for label, path in TRIAGE_MACHINES.items():
            slate, run_id = f"gate-{label}", f"gate-{label}"
            with self.subTest(machine=label):
                self._filed_and_covered(slate, REFERENCES / "cutoff-product.yaml",
                                        "--config", str(task_layer))
                for agent, batch, angle, extra in (("r1", "1", "reproduction-rerun", ()),
                                                   ("r2", "fresh-eye", "retry timing", ("--last",))):
                    attacked = self._attack(slate, agent, batch, angle, *extra)
                    self.assertEqual(attacked.returncode, 0, attacked.stderr)
                cutoff = self._converge("cutoff", slate, "--dir", str(self.ledgers))
                self.assertEqual(cutoff.returncode, 0, cutoff.stderr)
                ledger = self._triage_run(run_id, path, "triage-review")
                leave = ("--leave-arg", f"slate={slate}", "--leave-arg", f"base_slate={slate}",
                         "--leave-arg", f"converge_dir={self.ledgers}",
                         "--leave-arg", f"report={self.report}")
                row = "| F001 | x is None at a.py:10 | reproduced | uv run pytest -q | 1 failed |"
                gate_next = "disposition" if label == "override" else "succeeded"

                self._report([row], headings=("Cause", "Impact", "Confidence"))
                refused = self._move(run_id, gate_next, *leave)
                self.assertEqual(refused.returncode, 0, refused.stderr)
                self.assertIn("current: triage\n", ledger.read_text())
                self.assertIn("'triage-review' leave_check exited 1", refused.stdout)
                self.assertIn("report has no ## Next action heading", refused.stdout)
                self.assertIn("report has no ## Solutions heading", refused.stdout)

                self._report([row])
                self.assertEqual(self._move(run_id, "triage-review").returncode, 0)
                allowed = self._move(run_id, gate_next, *leave)
                self.assertEqual(allowed.returncode, 0, allowed.stderr)
                if gate_next == "disposition":
                    allowed = self._move(run_id, "succeeded")
                    self.assertEqual(allowed.returncode, 0, allowed.stderr)
                self.assertIn("current: succeeded\n", ledger.read_text())

    def test_triage_review_unresolved_report_walks_to_succeeded(self):
        task_layer = self.tmp / "rerun-only.yaml"
        task_layer.write_text(RERUN_ONLY)
        for label, path in TRIAGE_MACHINES.items():
            slate, run_id = f"unresolved-{label}", f"unresolved-{label}"
            with self.subTest(machine=label):
                self._filed_and_covered(slate, REFERENCES / "cutoff-product.yaml",
                                        "--config", str(task_layer))
                refuted = self._converge("attack", slate, "--dir", str(self.ledgers), "--as", "r1",
                                         "--claim", "F001", "--batch", "1",
                                         "--angle", "reproduction-rerun", "--tell", "tell applies",
                                         "--evidence", "re-ran it: passes",
                                         "--searches", "uv run pytest -q",
                                         "--positive-control", "the output names x")
                self.assertEqual(refuted.returncode, 0, refuted.stderr)
                declined = self._converge("reply", slate, "--dir", str(self.ledgers), "--as",
                                          "finder", "--claim", "F001", "--batch", "1",
                                          "--stance", "decline")
                self.assertEqual(declined.returncode, 0, declined.stderr)
                cutoff = self._converge("cutoff", slate, "--dir", str(self.ledgers))
                self.assertEqual(cutoff.returncode, 0, cutoff.stderr)
                ledger = self._triage_run(run_id, path, "triage-review")
                self._report(["| F001 | x is None at a.py:10 | reproduced | uv run pytest -q | 1 failed |"])
                self.report.write_text(self.report.read_text().replace(
                    "## Cause\n\nCause text.", "## Cause\n\nStatus: unresolved"))
                leave = ("--leave-arg", f"slate={slate}", "--leave-arg", f"base_slate={slate}",
                         "--leave-arg", f"converge_dir={self.ledgers}",
                         "--leave-arg", f"report={self.report}")
                gate_next = "disposition" if label == "override" else "succeeded"
                moved = self._move(run_id, gate_next, *leave)
                self.assertEqual(moved.returncode, 0, moved.stderr)
                if gate_next == "disposition":
                    moved = self._move(run_id, "succeeded")
                    self.assertEqual(moved.returncode, 0, moved.stderr)
                self.assertIn("current: succeeded\n", ledger.read_text())

    def test_check_x_gate_refuses_a_triage_slate_with_no_surviving_claim(self):
        self.assertEqual(self._slate("s1").returncode, 0)
        self._report()
        result = self._gate("s1")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("no claim survived; a triage slate needs at least one surviving "
                      "cause claim", result.stdout)

    def test_check_x_gate_refuses_a_surviving_claim_without_a_rerun_attack(self):
        self.assertEqual(self._slate("s1").returncode, 0)
        filed = self._file("s1", "x is None at a.py:10")
        self.assertEqual(filed.returncode, 0, filed.stderr)
        claim = filed.stdout.split()[1]
        self._report([(f"| {claim} | x is None at a.py:10 | reproduced | "
                       "uv run pytest -q | 1 failed |")])
        result = self._gate("s1")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(f"{claim} survived with no reproduction-rerun attack", result.stdout)
