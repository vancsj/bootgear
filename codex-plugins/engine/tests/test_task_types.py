"""C30a checks for the six engine task types, on the Codex host.

Host paths: `codex-plugins/engine/` (`scripts/task`, `scripts/converge`) and
the bootgear overrides in `.bootgear/config/`. The cross-host byte copies and the shared docs
are read from the repo root. Subprocesses run in scratch dirs, never in the repo.
"""
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from settlement_fixture import valid_settlement

PLUGIN_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
TASK_BIN = PLUGIN_DIR / "scripts" / "task"
CONVERGE_BIN = PLUGIN_DIR / "scripts" / "converge"
HOST_ROOT_VAR = "PLUGIN_ROOT"
ENGINE_SRC = PLUGIN_DIR / "src"
MACHINES = PLUGIN_DIR / "state-machines"
REFERENCES = PLUGIN_DIR / "references"
OVERRIDES = REPO_ROOT / ".bootgear" / "config"
TASK_TYPES = ("ticket-writing", "ticket-to-pr", "triage", "change-review", "design-doc", "artefact-review")
# Static project override node sets.
OVERRIDE_NODES = {
    "change-review": {"clarify", "disposition", "failed", "fix", "inspect", "review",
                      "review-debate", "spec", "spec-review", "spec-debate", "succeeded"},
    "triage": {"clarify", "disposition", "failed", "inspect", "succeeded", "triage", "triage-debate",
               "triage-review"},
    "ticket-writing": {"clarify", "failed", "inspect", "succeeded", "ticket", "ticket-debate",
                       "ticket-review"},
}
# D3 profiles, with each reach and impact set sorted.
PRODUCT_RULE = {"reach": ["crafted", "normal"],
                "impact": ["clarity", "data-loss", "security", "wrong-output"]}
UNREACHABLE_RULE = {"reach": ["unreachable"], "impact": ["data-loss", "security", "wrong-output"]}
# Every cause claim is attacked, so each surviving claim can carry a reproduction-rerun attack.
EVERY_CLAIM_RULE = {"reach": ["crafted", "normal", "unreachable"]}
TRIAGE_PROFILES = {"product": REFERENCES / "cutoff-product.yaml",
                   "one-user": OVERRIDES / "cutoff-one-user.yaml"}
TRIAGE_MACHINES = {"built-in": MACHINES / "triage.yaml",
                   "override": OVERRIDES / "state-machine-triage.yaml"}
# The triage nodes after clarify, in walk order.
TRIAGE_WALK = ("inspect", "triage", "triage-review")
GATE_CHECK = ["converge", "gate", "{slate}", "--dir", "{converge_dir}", "--kind", "triage",
              "--base-slate", "{base_slate}", "--report", "{report}"]
# A task layer that leaves `reproduction-rerun` as the only attack angle and skips cuts.
RERUN_ONLY = """\
steps: {cut: none, gap_hunt: false, escalate: false}
angles:
  disable: [cited-but-unread, point-in-time, provenance, reachability, absent-vs-default,
            downstream-consumer, inverse-reading, carve-out, boundary, dependents,
            positive-control, inherited-bounds, guarded-elsewhere, deliberate, real-referent]
"""
CUT_EVIDENCE = ("--evidence", "entry-points=no caller reaches it",
                "--evidence", "blast-radius=one row per call",
                "--evidence", "affected-count=one record",
                "--evidence", "files-touched=a.py")
# The docs/engine.md overview writes the types in prose.
PROSE_NAMES = {
    "ticket writing": "ticket-writing",
    "ticket-to-pr": "ticket-to-pr",
    "triage": "triage",
    "change review": "change-review",
    "design docs": "design-doc",
    "artefact review": "artefact-review",
}
# A reminder that names `spec` as the skill to draft with. A "does not: call `spec`" clause
# does not match.
DRAFT_WITH_SPEC = re.compile(r"\b(?:with|using|via|by)\s+(?:the\s+)?`?(?:/|\$)?spec`?(?![\w-])")
SCRUBBED = ("BOOTGEAR_OUTPUT", "BOOTGEAR_PROG", "GEAR_CALLER_CWD", "VIRTUAL_ENV",
            "BOOTGEAR_HOST", "CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT")
SETTLEMENT_MACHINE = """\
name: fixture
nodes:
  clarify:
    next: [ticket]
  ticket:
    next: [ticket-review]
  ticket-review:
    next: [succeeded]
  succeeded:
    terminal: true
  failed:
    terminal: true
"""
BODY = """\
## Problem
The export drops rows.

## Outcome
Every row exports.

## Acceptance criteria
- An export of 3 rows has 3 rows.

## Scope
The export command only.

## Verification notes
Run the export on the fixture.
"""


def _uv_dirs() -> dict[str, str]:
    """The real uv cache and Python dirs, so a scratch HOME does not force a download."""
    env: dict[str, str] = {}
    for var, cmd in (("UV_CACHE_DIR", ["uv", "cache", "dir"]),
                     ("UV_PYTHON_INSTALL_DIR", ["uv", "python", "dir"])):
        if var in os.environ:
            env[var] = os.environ[var]
            continue
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except OSError:
            continue
        if out.returncode == 0 and out.stdout.strip():
            env[var] = out.stdout.strip()
    return env


UV_DIRS = _uv_dirs()


def _env(home: Path | None = None) -> dict[str, str]:
    """This host's wrapper environment: prose output, this host's root, no caller or other host."""
    env = {key: value for key, value in os.environ.items() if key not in SCRUBBED}
    env["BOOTGEAR_OUTPUT"] = "prose"
    env[HOST_ROOT_VAR] = str(PLUGIN_DIR)
    if home is not None:
        env.update(UV_DIRS)
        env["HOME"] = str(home)
    return env


def _load_yaml(path: Path):
    return yaml.safe_load(path.read_text())


def _session_module():
    if str(ENGINE_SRC) not in sys.path:
        sys.path.insert(0, str(ENGINE_SRC))
    return importlib.import_module("engine.session")


def _rule(rule: dict) -> dict:
    """A cutoff rule's sorted reach and impact sets. `status` is a report filter, not a D3 criterion."""
    return {key: sorted(value) for key, value in rule.items() if key != "status"}


class Scratch(unittest.TestCase):
    """Each test gets its own project, session dir, converge ledgers and HOME."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engine-task-types-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.project = self.tmp / "project"
        self.project.mkdir()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.session_dir = self.tmp / "session"
        self.ledgers = self.tmp / "ledgers"
        self.ledgers.mkdir()
        self.report = self.tmp / "report.md"

    def _task(self, *args):
        return subprocess.run([str(TASK_BIN), *args], capture_output=True, text=True,
                              check=False, cwd=self.project, env=_env())

    def _converge(self, *args):
        return subprocess.run([str(CONVERGE_BIN), *args], capture_output=True, text=True,
                              check=False, cwd=self.project, env=_env(self.home))

    # -- settlements and ledgers -------------------------------------------------------

    def _settlement(self, task_type, extra=""):
        text = valid_settlement(SETTLEMENT_MACHINE, extra=extra)
        return text.replace("task_type: ticket-to-pr\n", f"task_type: {task_type}\n", 1)

    def _validate(self, task_type, extra=""):
        path = self.tmp / f"settlement-{task_type}.txt"
        path.write_text(self._settlement(task_type, extra) + f"session_dir: {self.session_dir}\n")
        return self._task("session", "validate", "run-1", "--dir", str(self.session_dir),
                          "--settlement-file", str(path), "--prose")

    def _init(self, run_id, task_type, extra="", *flags):
        path = self.tmp / f"init-{run_id}.txt"
        path.write_text(self._settlement(task_type, extra))
        return self._task("session", "init", run_id, "--dir", str(self.session_dir),
                          "--settlement-file", str(path), "--prose", *flags)

    def _ledger(self, run_id, task_type, stored=""):
        """An initialized ledger; `stored` lines are added to its stored settlement."""
        result = self._init(run_id, task_type)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.session_dir / f"{run_id}.md"
        if stored:
            text = path.read_text()
            path.write_text(text.replace("\n\n## decisions\n",
                                         f"\n{stored.rstrip()}\n\n## decisions\n", 1))
        return path

    def _ticket(self, run_id):
        return self.session_dir / f"{run_id}.artifacts" / "issue.md"

    def _ticket_run(self, run_id="tw-run"):
        ledger = self._ledger(run_id, "ticket-writing")
        moved = self._task("state", "transition", run_id, "--dir", str(self.session_dir),
                           "--to", "ticket", "--reason", "draft the body", "--prose")
        self.assertEqual(moved.returncode, 0, moved.stderr)
        return ledger

    def _write(self, run_id, body):
        body_file = self.tmp / f"body-{run_id}.md"
        body_file.write_text(body)
        return self._task("session", "write-ticket", run_id, "--dir", str(self.session_dir),
                          "--body-file", str(body_file), "--prose")

    # -- converge slates ---------------------------------------------------------------

    def _slate(self, slate, defaults=REFERENCES / "cutoff-product.yaml", *extra):
        return self._converge("init", slate, "--dir", str(self.ledgers), "--as", "orch",
                              "--project-root", str(self.project), "--lenses", "default",
                              "--defaults", str(defaults),
                              "--angles", str(REFERENCES / "angles-triage.yaml"), *extra)

    def _file(self, slate, claim):
        return self._converge("file", slate, "--dir", str(self.ledgers), "--as", "finder",
                              "--loc", "src/a.py:10", "--claim", claim,
                              "--trigger", "caller passes None", "--origin", "lens",
                              "--evidence", "a.py:10 reads x.y with x None",
                              "--tier", "reproduced", "--lens", "default",
                              "--angle", "report-claim")

    def _filed_and_covered(self, slate, defaults=REFERENCES / "cutoff-product.yaml", *extra):
        """A slate with claim F001 and complete find coverage; the find-run output."""
        self.assertEqual(self._slate(slate, defaults, *extra).returncode, 0)
        filed = self._file(slate, "x is None at a.py:10")
        self.assertEqual(filed.returncode, 0, filed.stderr)
        covered = self._converge("find-run", slate, "--dir", str(self.ledgers), "--as", "finder",
                                 "--lens", "default", "--angle", "report-claim",
                                 "--tell", "the report has one row",
                                 "--searches", "the ## Claims table",
                                 "--positive-control", "row F001 is found", "--result", "F001")
        self.assertEqual(covered.returncode, 0, covered.stderr)
        return covered

    def _attack(self, slate, agent, batch, angle, *extra):
        return self._converge("attack", slate, "--dir", str(self.ledgers), "--as", agent,
                              "--claim", "F001", "--batch", batch, "--angle", angle,
                              "--tell", "tell applies",
                              "--outcome", "clean", "--evidence", "re-ran it: 1 failed",
                              "--searches", "uv run pytest -q",
                              "--positive-control", "the output names x", *extra)

    def _report(self, rows=(), headings=("Cause", "Impact", "Confidence", "Next action",
                                             "Solutions")):
        lines = ["# Triage report", "", "## Claims", "",
                 "| id | claim | tier | command | output |", "|---|---|---|---|---|", *rows]
        for heading in headings:
            body = "- no-fact: fixture reason." if heading == "Solutions" else f"{heading} text."
            lines += ["", f"## {heading}", "", body]
        self.report.write_text("\n".join(lines) + "\n")

    # -- triage runs -------------------------------------------------------------------

    def _move(self, run_id, dest, *extra):
        """`task state transition`, with this host's converge first on PATH for leave checks."""
        env = _env(self.home)
        env["PATH"] = f"{CONVERGE_BIN.parent}{os.pathsep}{env.get('PATH', '')}"
        return subprocess.run([str(TASK_BIN), "state", "transition", run_id, "--dir",
                               str(self.session_dir), "--to", dest, "--reason", f"to {dest}",
                               "--confirm-leave", *extra, "--prose"],
                              capture_output=True, text=True, check=False, cwd=self.project,
                              env=env)

    def _triage_run(self, run_id, machine, node):
        """A triage run on the `machine` file, walked from clarify to `node`."""
        path = self.tmp / f"init-{run_id}.txt"
        text = valid_settlement(machine.read_text(), extra="triage_cutoff: product\n")
        path.write_text(text.replace("task_type: ticket-to-pr\n", "task_type: triage\n", 1))
        result = self._task("session", "init", run_id, "--dir", str(self.session_dir),
                            "--settlement-file", str(path), "--prose")
        self.assertEqual(result.returncode, 0, result.stderr)
        for dest in TRIAGE_WALK[:TRIAGE_WALK.index(node) + 1]:
            moved = self._move(run_id, dest)
            self.assertEqual(moved.returncode, 0, moved.stderr)
        return self.session_dir / f"{run_id}.md"

    def _gate(self, slate):
        return self._converge("gate", slate, "--dir", str(self.ledgers), "--kind", "triage",
                              "--report", str(self.report))


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

    def test_check_vi_product_cutoff_and_triage_angles_are_byte_identical_on_both_hosts(self):
        for rel in ("references/cutoff-product.yaml", "references/angles-triage.yaml"):
            with self.subTest(file=rel):
                claude = (REPO_ROOT / "plugins" / "engine" / rel).read_bytes()
                codex = (REPO_ROOT / "codex-plugins" / "engine" / rel).read_bytes()
                self.assertEqual(claude, codex)

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


class GateChecks(Scratch):
    def test_check_ix_cutoff_profiles_match_d3_and_converge_init_exits_0(self):
        profiles = {
            REPO_ROOT / "plugins" / "engine" / "references" / "cutoff-product.yaml":
                [PRODUCT_RULE, EVERY_CLAIM_RULE],
            REPO_ROOT / "codex-plugins" / "engine" / "references" / "cutoff-product.yaml":
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
        # Positive control: the same profile without its `steps` opens the gap hunt.
        without_steps = _load_yaml(TRIAGE_PROFILES["product"])
        without_steps.pop("steps", None)
        control = self.tmp / "cutoff-no-steps.yaml"
        control.write_text(yaml.safe_dump(without_steps))
        self.assertIn("next: gap hunt: r2 files", self._filed_and_covered("gap-on", control).stdout)

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
                                         "--outcome", "refuted", "--evidence", "re-ran it: passes",
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


if __name__ == "__main__":
    unittest.main()
