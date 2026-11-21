import json
import re
import unittest

import yaml
from task_types_test_support import (
    BODY,
    DRAFT_WITH_SPEC,
    MACHINES,
    OVERRIDE_NODES,
    OVERRIDES,
    PLUGIN_DIR,
    PROSE_NAMES,
    REPO_ROOT,
    TASK_TYPES,
    Scratch,
    _load_yaml,
    _session_module,
)


class StaticChecks(Scratch):
    def test_check_i_task_types_are_the_six_values(self):
        self.assertEqual(set(_session_module().TASK_TYPES), set(TASK_TYPES))

    def test_check_ii_each_builtin_machine_validates(self):
        for task_type in TASK_TYPES:
            with self.subTest(task_type=task_type):
                result = self._task("state", "validate", str(MACHINES / f"{task_type}.yaml"))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.endswith(": ok\n"), result.stdout)

    def test_check_iv_ticket_writing_has_no_spec_node_and_no_spec_draft_reminder(self):
        nodes = _load_yaml(MACHINES / "ticket-writing.yaml")["nodes"]
        self.assertEqual([name for name in nodes if name.startswith("spec")], [])
        # The pattern itself must match a drafting reminder, or the check below proves nothing.
        self.assertIsNotNone(DRAFT_WITH_SPEC.search("Draft the body with `spec`."))
        for name, node in nodes.items():
            do = (node.get("reminder") or {}).get("do", "")
            with self.subTest(node=name):
                self.assertIsNone(DRAFT_WITH_SPEC.search(do))

    def test_check_v_design_doc_has_no_impl_node(self):
        self.assertNotIn("impl", _load_yaml(MACHINES / "design-doc.yaml")["nodes"])

    def test_product_cutoff_and_triage_angles_have_one_shared_location(self):
        for rel in ("references/cutoff-product.yaml", "references/angles-triage.yaml"):
            matches = list((REPO_ROOT / "plugins").glob(f"*/{rel}"))
            self.assertEqual(matches, [PLUGIN_DIR / rel])
            self.assertTrue(yaml.safe_load(matches[0].read_text()))

    def test_check_vii_every_copy_of_the_six_value_list_names_the_same_values(self):
        clarify = (PLUGIN_DIR / "skills" / "clarify" / "SKILL.md").read_text()
        clarify_list = re.search(r"^2\. \*\*Task type\*\*[^\n]*:\n((?:   - [^\n]*\n)+)",
                                 clarify, re.MULTILINE)
        assert clarify_list is not None, "clarify item 2 has no type list"
        engine_doc = (REPO_ROOT / "docs" / "engine.md").read_text()
        overview = re.search(r"drives one task \(([^)]*)\)", engine_doc)
        task_field = re.search(r"`task_type` \(one of ([^)]*)\)", engine_doc)
        state_doc = (REPO_ROOT / "docs" / "state-machine.md").read_text()
        built_in = re.search(r"There is one for each task type: ([^.]*)\.", state_doc)
        readme = (REPO_ROOT / "plugins" / "engine" / "README.md").read_text()
        table_row = re.search(r"^\| Task type \| exactly one of ([^|]*) \|", readme, re.MULTILINE)
        assert overview and task_field and built_in and table_row, "a type list is missing"
        copies = {
            "clarify list": re.findall(r"^   - `([a-z-]+)` — ", clarify_list.group(1),
                                       re.MULTILINE),
            "TASK_TYPES": sorted(_session_module().TASK_TYPES),
            "docs/engine.md overview": [
                PROSE_NAMES[item.strip().casefold()]
                for item in " ".join(overview.group(1).split()).split(",")],
            "docs/engine.md task_type": re.findall(r"`([a-z-]+)`", task_field.group(1)),
            "docs/state-machine.md": re.findall(r"`([a-z-]+)`", built_in.group(1)),
            "plugins/engine/README.md": re.findall(r"`([a-z-]+)`", table_row.group(1)),
        }
        for label, names in copies.items():
            with self.subTest(copy=label):
                self.assertEqual(sorted(names), sorted(TASK_TYPES))

    def test_d6_override_node_sets_are_the_expected_sets(self):
        for task_type, expected in OVERRIDE_NODES.items():
            with self.subTest(task_type=task_type):
                path = OVERRIDES / f"state-machine-{task_type}.yaml"
                self.assertEqual(set(_load_yaml(path)["nodes"]), expected)


class TriageCutoffChecks(Scratch):
    def test_check_iii_triage_accepts_product(self):
        result = self._validate("triage", "triage_cutoff: product\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_iii_triage_refuses_a_missing_cutoff(self):
        result = self._validate("triage")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("  triage_cutoff (1):\n", result.stderr)
        self.assertIn("is required for a triage run", result.stderr)

    def test_check_iii_triage_refuses_a_cutoff_outside_the_set(self):
        result = self._validate("triage", "triage_cutoff: strict\n")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("must be one of: product, one-user", result.stderr)

    def test_check_iii_another_type_refuses_a_cutoff(self):
        result = self._validate("ticket-to-pr", "triage_cutoff: product\n")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("only a triage run has one, not 'ticket-to-pr'", result.stderr)

    def test_check_iii_all_problems_appear_in_one_message(self):
        result = self._validate("ticket-to-pr",
                                "triage_cutoff: strict\ndebate_mode: sometimes\n")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("3 problem(s)", result.stderr)
        self.assertIn("only a triage run has one, not 'ticket-to-pr'", result.stderr)
        self.assertIn("must be one of: product, one-user", result.stderr)
        self.assertIn("  debate_mode (1):\n", result.stderr)


class TicketChecks(Scratch):
    def test_check_viii_settlement_refuses_each_bad_stored_ticket_path(self):
        canonical = self._ticket("tw-run")
        cases = {
            '""': "must not be empty",
            '"-issue.md"': "must not start with '-'",
            f'"{canonical}\\nmore"': "must not contain a line break",
            '"drafts/issue.md"': "must be an absolute path",
            f'"{self.tmp / "elsewhere" / "issue.md"}"': f"must equal {canonical}",
        }
        for value, message in cases.items():
            with self.subTest(value=value):
                (self.session_dir / "tw-run.md").unlink(missing_ok=True)
                self._ledger("tw-run", "ticket-writing", f"ticket_path: {value}")
                result = self._task("session", "validate", "tw-run", "--dir",
                                    str(self.session_dir), "--prose")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("  ticket_path (", result.stderr)
                self.assertIn(f"    - {message}\n", result.stderr)

    def test_check_viii_settlement_accepts_the_canonical_ticket_path(self):
        (self.session_dir / "tw-run.md").unlink(missing_ok=True)
        self._ledger("tw-run", "ticket-writing",
                     f"ticket_path: {json.dumps(str(self._ticket('tw-run')))}")
        result = self._task("session", "validate", "tw-run", "--dir", str(self.session_dir),
                            "--prose")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_viii_and_xii_write_verb_refuses_an_unowned_file_and_leaves_it_unchanged(self):
        ledger = self._ticket_run()
        ticket = self._ticket("tw-run")
        ticket.parent.mkdir()
        ticket.write_text("written by a host tool\n")
        before = ledger.read_text()
        result = self._write("tw-run", BODY)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("this run does not own it", result.stderr)
        self.assertEqual(ticket.read_text(), "written by a host tool\n")
        self.assertEqual(ledger.read_text(), before)

    def test_check_xii_redraft_of_an_owned_body_is_allowed(self):
        self._ticket_run()
        self.assertEqual(self._write("tw-run", BODY).returncode, 0)
        redraft = BODY.replace("drops rows", "drops the last row")
        result = self._write("tw-run", redraft)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._ticket("tw-run").read_text(), redraft)

    def test_check_xii_init_force_refuses_a_ledger_that_owns_artifacts(self):
        ledger = self._ticket_run()
        self.assertEqual(self._write("tw-run", BODY).returncode, 0)
        before = ledger.read_text()
        result = self._init("tw-run", "ticket-writing", "", "--force")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("lists owned artifacts", result.stderr)
        self.assertEqual(ledger.read_text(), before)

    def test_check_xiii_write_verb_refuses_a_body_missing_a_heading(self):
        ledger = self._ticket_run()
        before = ledger.read_text()
        body = BODY.replace("## Verification notes\n", "Verification notes\n")
        result = self._write("tw-run", body)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("no 'Verification notes' heading", result.stderr)
        self.assertFalse(self._ticket("tw-run").exists())
        self.assertEqual(ledger.read_text(), before)


if __name__ == "__main__":
    unittest.main()
