"""Exercise writing checks and author records through the public executable."""
import concurrent.futures
import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
REPO = PLUGIN.parents[1]
HOST = os.environ.get("BOOTGEAR_TEST_HOST", "claude")
COMMAND = [str(REPO / "plugins" / "cli" / "bin" / "gear"), "--host", HOST,
           "--root", str(REPO), "review", "self-review"]
PROGRAM = shlex.join([COMMAND[0], "--host", HOST, "review", "self-review"])


class SelfReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.task = self.root / "task"
        self.project = self.root / "project"
        self.project.mkdir()

    def call(self, command, data=None, stage="spec", expected=0):
        argv = [*COMMAND, command, "--task-folder", str(self.task),
                "--project-root", str(self.project), "--stage", stage, "--json"]
        if data is not None:
            argv += ["--input", "-"]
        result = subprocess.run(argv, input=json.dumps(data) if data is not None else None,
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def open(self, data=None, stage="spec"):
        return self.call("open", data if data is not None else {"candidates": [], "selections": []}, stage)

    def record(self, number, result="found", stage="spec", refs=None, expected=0):
        return self.call("pass", {"expected_pass": number, "result": result,
                                 "unresolved_refs": refs or []}, stage, expected)

    def source(self, name, mode="absorb", scope="selected phases: authoring; orchestration"):
        return {"name": name, "mode": mode, "scope": scope, "coverage": "Applies to this artifact.",
                "confirmation": {"kind": "user-message", "ref": "conversation:choice-1"}}

    def writing_file(self, text, name="guide.md"):
        source = self.root / name
        source.write_text(text)
        return source

    def writing_check(self, files, kind="procedure", expected=0):
        result = subprocess.run([*COMMAND, "check", "--kind", kind, "--files",
                                 *map(str, files), "--json"],
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["check_kind"], "mechanical-writing")
        self.assertEqual(report["kind"], kind)
        self.assertTrue(report["next"])
        return report

    def test_empty_status_is_successful_and_creates_nothing(self):
        status = self.call("status")
        self.assertFalse(status["record_exists"])
        self.assertEqual(status["checkpoints"], [])
        self.assertFalse(self.task.exists())

    def test_writing_check_runs_without_checkpoint_arguments(self):
        source = self.root / "guide.md"
        source.write_text("Read the guide before you start.\n")
        result = subprocess.run([*COMMAND, "check", "--kind", "procedure", "--files", str(source), "--json"],
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["check_kind"], "mechanical-writing")
        self.assertEqual(report["outcome"], "passed")
        self.assertFalse(self.task.exists())

    def test_checkpoint_result_identifies_author_record(self):
        self.assertEqual(self.open()["check_kind"], "author-record")
        self.assertEqual(self.record(1, "clean")["check_kind"], "author-record")
        result = subprocess.run([*COMMAND, "status", "--task-folder", str(self.task), "--prose"],
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Outcome: clean (author-reported)", result.stdout)

    def test_writing_sentence_limits_include_the_boundary(self):
        sentences = {
            "procedure": "Read the guide and check each setting before you start the service "
                         "on the shared test system for this task",
            "description": "The service shows the latest result and gives the author a clear next action "
                           "after each check of the selected files in the current task",
        }
        for kind, limit in (("procedure", 20), ("description", 25)):
            with self.subTest(kind=kind):
                sentence = sentences[kind]
                source = self.writing_file(sentence + ".\n")
                passed = self.writing_check([source], kind)
                self.assertEqual(passed["outcome"], "passed")
                self.assertEqual(passed["findings"], [])
                self.assertEqual(passed["diagnostics"], [])
                source.write_text(sentence + " today.\n")
                report = self.writing_check([source], kind, expected=1)
                self.assertEqual(report["outcome"], "needs-reading")
                self.assertEqual(report["findings"], [{"path": str(source), "line": 1,
                                                       "words": limit + 1, "limit": limit,
                                                       "text": sentence + " today."}])

    def test_writing_counts_visible_links_and_inline_code_without_code_blocks(self):
        sentence = ("Read the [guide](https://example.com/a.long/path?section=setup) and check each setting "
                    "before you run `service.start --mode fast` on the shared test system for this new task")
        source = self.writing_file("# " + "A heading with many words " * 8 + "\n\n"
                                   "```text\n" + "This is code with many words " * 8 + "\n```\n\n"
                                   "~~~shell\n" + "This is also code with many words " * 8 + "\n~~~\n\n"
                                   + sentence + ".\n")
        self.assertEqual(self.writing_check([source])["outcome"], "passed")
        source.write_text(sentence + " today.\n")
        report = self.writing_check([source], expected=1)
        self.assertEqual([item["words"] for item in report["findings"]], [21])
        self.assertNotIn("https://", report["findings"][0]["text"])

    def test_writing_preserves_wrapped_list_and_table_locations_and_groups_files(self):
        start = "Read the guide and check each setting before you start"
        end = "the service on the shared test system for this task today."
        sentence = start + " " + end
        source = self.writing_file("# Guide\n\n" + start + "\n" + end + "\n\n"
                                   "- " + start + "\n  " + end + "\n\n"
                                   "| Action | Note |\n| --- | --- |\n| " + sentence + " | Read it. |\n")
        other = self.writing_file(sentence + "\n", "notes.md")
        report = self.writing_check([source, other], expected=1)
        self.assertEqual(report["checked_files"], [str(source), str(other)])
        self.assertEqual([(item["path"], item["line"], item["words"], item["limit"])
                          for item in report["findings"]],
                         [(str(source), 3, 21, 20), (str(source), 6, 21, 20),
                          (str(source), 11, 21, 20), (str(other), 1, 21, 20)])
        self.assertEqual({item["text"] for item in report["findings"]}, {sentence})

    def test_writing_counts_hyphens_parentheses_and_list_colons(self):
        source = self.writing_file(
            "Read the guide and check each setting before you start the service "
            "on the shared-test system for this task today.\n\n"
            "Read the guide and check each setting (if the service is ready) before you start "
            "the service on the shared system for this task.\n\n"
            "Read the guide and check each setting before you start the service "
            "on the shared test system for this task:\n- Read the report.\n")
        self.assertEqual(self.writing_check([source])["outcome"], "passed")
        source.write_text("Read the guide (the service shows the latest result and gives the author "
                          "a clear next action after each check of the selected files).\n")
        report = self.writing_check([source], expected=1)
        self.assertEqual([(item["line"], item["words"], item["limit"])
                          for item in report["findings"]], [(1, 21, 20)])
        source.write_text("Read the guide and check each setting (if ready) before you start the service "
                          "on the shared test system for this task.\n")
        report = self.writing_check([source], expected=1)
        self.assertEqual([item["words"] for item in report["findings"]], [21])
        source.write_text("Read the guide and check each setting before you start the service "
                          "on the shared test system for this task: read the report.\n")
        report = self.writing_check([source], expected=1)
        self.assertEqual([item["words"] for item in report["findings"]], [23])

    def test_writing_single_column_tables_and_wrapped_link_labels_keep_source_lines(self):
        sentence = ("Read the guide and check each setting before you start the service "
                    "on the shared test system for this task today.")
        for markdown, line in (("| Guide |\n| --- |\n| " + sentence + " |\n", 3),
                               ("[Read it.\n" + sentence + "](https://example.com/guide)\n", 2)):
            with self.subTest(markdown=markdown):
                source = self.writing_file(markdown)
                report = self.writing_check([source], expected=1)
                self.assertEqual([(item["line"], item["words"]) for item in report["findings"]], [(line, 21)])

    def test_writing_emphasis_keeps_sentence_boundaries_and_real_findings(self):
        first = "Read the guide and check each setting before you start."
        second = "Run the service on the shared test system for this task."
        long = ("Read the guide and check each setting before you start the service "
                "on the shared test system for this task today.")
        for marker in ("*", "**", "_", "__"):
            with self.subTest(marker=marker):
                source = self.writing_file(f"{marker}{first}{marker} {second}\n")
                self.assertEqual(self.writing_check([source])["findings"], [])
                source.write_text(f"{marker}{long}{marker} Read it.\n")
                report = self.writing_check([source], expected=1)
                self.assertEqual([(item["line"], item["words"]) for item in report["findings"]], [(1, 21)])

    def test_writing_excludes_list_fences_and_keeps_following_prose(self):
        sentence = ("Read the guide and check each setting before you start the service "
                    "on the shared test system for this task today.")
        for fence in ("```", "~~~"):
            with self.subTest(fence=fence):
                source = self.writing_file("1. Read the report.\n\n    " + fence + "text\n    "
                                           + sentence + "\n\n    " + fence + "\n")
                self.assertEqual(self.writing_check([source])["findings"], [])
                source.write_text(source.read_text() + "\n    " + sentence + "\n")
                report = self.writing_check([source], expected=1)
                self.assertEqual([(item["line"], item["words"]) for item in report["findings"]], [(8, 21)])

    def test_writing_marker_fences_exclude_code_and_keep_following_prose(self):
        sentence = ("Read the guide and check each setting before you start the service "
                    "on the shared test system for this task today.")
        for prefix in ("1. ", "- ", "10. ", "  + "):
            for fence in ("```", "~~~"):
                with self.subTest(prefix=prefix, fence=fence):
                    indent = " " * len(prefix)
                    source = self.writing_file(prefix + fence + "text\n" + indent + sentence
                                               + "\n" + indent + fence + "\n\n" + indent + sentence + "\n")
                    report = self.writing_check([source], expected=1)
                    self.assertEqual([(item["line"], item["words"]) for item in report["findings"]],
                                     [(5, 21)])

    def test_writing_checkbox_same_line_fence_is_prose_and_keeps_following_paragraph(self):
        sample = ("Run the service and inspect each new setting before you send the check result "
                  "to the team on the shared system for this task.")
        following = ("Read the guide and check each setting before you start the service "
                     "on the shared test system for this task today.")
        source = self.writing_file(f"- [ ] ```text\n  {sample}\n  ```\n\n{following}\n")
        report = self.writing_check([source], expected=1)
        self.assertEqual(len(report["findings"]), 2)
        self.assertIn(sample, report["findings"][0]["text"])
        self.assertEqual((report["findings"][1]["line"], report["findings"][1]["text"]), (5, following))

    def test_writing_checkbox_separate_fence_excludes_code_and_keeps_following_prose(self):
        sample = ("Run the service and inspect each new setting before you send the check result "
                  "to the team on the shared system for this task.")
        following = ("Read the guide and check each setting before you start the service "
                     "on the shared test system for this task today.")
        for indent, after in (("  ", f"  {following}"), ("      ", following)):
            source = self.writing_file(f"- [ ] Read the report.\n\n{indent}```text\n\n"
                                       f"{indent}{sample}\n\n{indent}```\n\n{after}\n")
            report = self.writing_check([source], expected=1)
            self.assertEqual([(item["line"], item["text"]) for item in report["findings"]], [(9, following)])

    def test_writing_inline_code_at_list_start_keeps_following_prose(self):
        sentence = ("Read the guide and check each setting before you start the service "
                    "on the shared test system for this task today.")
        for prefix in ("1. ", "- "):
            with self.subTest(prefix=prefix):
                source = self.writing_file(prefix + "```shared settings``` " + sentence
                                           + "\n\n" + " " * len(prefix) + sentence + "\n")
                report = self.writing_check([source], expected=1)
                self.assertEqual([(item["line"], item["words"]) for item in report["findings"]],
                                 [(1, 22), (3, 21)])

    def test_writing_lazy_inline_code_does_not_hide_prose(self):
        sentence = ("Use ```shared settings``` and check each setting before you start the service "
                    "on the shared test system for this new task today.")
        following = ("Read the guide and check each setting before you start the service "
                     "on the shared test system for this task today.")
        for indent in ("", "   "):
            with self.subTest(indent=indent):
                source = self.writing_file("1. Read the report.\n" + indent + sentence
                                           + "\n\n   " + following + "\n")
                report = self.writing_check([source], expected=1)
                self.assertEqual([(item["line"], item["words"]) for item in report["findings"]],
                                 [(2, 21), (4, 21)])

    def test_writing_lazy_list_continuation_keeps_fence_context(self):
        sentence = ("Read the guide and check each setting before you start the service "
                    "on the shared test system for this task today.")
        for fence in ("```", "~~~"):
            with self.subTest(fence=fence):
                source = self.writing_file("1. Read the report.\nContinue this list item.\n\n    "
                                           + fence + "text\n    " + sentence + "\n\n    " + fence + "\n")
                self.assertEqual(self.writing_check([source])["findings"], [])
                source.write_text(source.read_text() + "\n    " + sentence + "\n")
                report = self.writing_check([source], expected=1)
                self.assertEqual([(item["line"], item["words"]) for item in report["findings"]], [(9, 21)])

    def test_writing_root_fence_after_list_keeps_following_prose(self):
        sentence = ("Read the guide and check each setting before you start the service "
                    "on the shared test system for this task today.")
        source = self.writing_file("1. Read the report.\n```text\n" + sentence
                                   + "\n\n```\n\n" + sentence + "\n")
        report = self.writing_check([source], expected=1)
        self.assertEqual([(item["line"], item["words"]) for item in report["findings"]], [(7, 21)])

    def test_writing_indented_literal_fence_keeps_following_prose(self):
        sentence = ("Read the guide and check each setting before you start the service "
                    "on the shared test system for this task today.")
        source = self.writing_file("    ```text\n    Read it.\n\n" + sentence + "\n")
        report = self.writing_check([source], expected=1)
        self.assertEqual([(item["line"], item["words"]) for item in report["findings"]], [(4, 21)])

    def test_writing_reports_all_read_failures_and_keeps_text_findings(self):
        source = self.writing_file("Read the guide and check each setting before you start the service "
                                   "on the shared test system for this task today.\n")
        missing = self.root / "missing.md"
        directory = self.root / "notes"
        directory.mkdir()
        report = self.writing_check([missing, source, directory], expected=3)
        self.assertEqual(report["outcome"], "unavailable")
        self.assertEqual(report["checked_files"], [str(source)])
        self.assertEqual([item["path"] for item in report["diagnostics"]], [str(missing), str(directory)])
        self.assertTrue(all(item["message"] for item in report["diagnostics"]))
        self.assertEqual([(item["path"], item["words"]) for item in report["findings"]], [(str(source), 21)])
        self.assertFalse(self.task.exists())

    def test_writing_check_preserves_files_checkpoint_and_pass_budget(self):
        self.open()
        self.record(1)
        source = self.writing_file("Read the guide and check each setting before you start the service "
                                   "on the shared test system for this task today.\n")
        files_before = {path.relative_to(self.root): path.read_bytes()
                        for path in self.root.rglob("*") if path.is_file()}
        self.writing_check([source], expected=1)
        files_after = {path.relative_to(self.root): path.read_bytes()
                       for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(files_after, files_before)
        self.assertEqual(self.call("status")["passes"], 1)

    def test_writing_relative_paths_and_output_modes_report_scope(self):
        source = self.writing_file("Read the guide.\n")
        base_env = dict(os.environ, GEAR_CALLER_CWD=str(self.root))
        for setting, flags, json_output in ((None, [], False), ("json", [], True),
                                            ("prose", [], False), ("json", ["--prose"], False),
                                            ("prose", ["--json"], True)):
            with self.subTest(setting=setting, flags=flags):
                env = dict(base_env)
                env.pop("BOOTGEAR_OUTPUT", None)
                if setting is not None:
                    env["BOOTGEAR_OUTPUT"] = setting
                result = subprocess.run([*COMMAND, "check", "--kind", "procedure", "--files", source.name, *flags],
                                        text=True, capture_output=True, check=False, env=env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                if json_output:
                    report = json.loads(result.stdout)
                    self.assertEqual(report["checked_files"], [str(source)])
                    for field in ("checks", "counting_policy", "limitations", "next"):
                        self.assertTrue(report[field], field)
                else:
                    self.assertIn("passed", result.stdout)
                    self.assertIn("mechanical writing", result.stdout.lower())
                    self.assertTrue(result.stdout.splitlines()[-1].lower().startswith("next:"))

    def test_writing_usage_errors_give_check_example_and_supported_commands(self):
        source = self.writing_file("Read the guide.\n")
        for flags in (("--files", str(source)), ("--kind", "procedure"),
                      ("--kind", "prose", "--files", str(source))):
            with self.subTest(flags=flags):
                result = subprocess.run([*COMMAND, "check", *flags], text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                output = result.stdout + result.stderr
                for fragment in ("Example:", "check --kind procedure --files", "Commands:", "status", "Next:"):
                    self.assertIn(fragment, output)
                result = subprocess.run([*COMMAND, "check", *flags, "--json"],
                                        text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                report = json.loads(result.stdout + result.stderr)
                self.assertEqual(report["check_kind"], "mechanical-writing")
                self.assertEqual(report["outcome"], "refused")
                self.assertIn("check --kind procedure --files", report["example"])
                self.assertIn("check", report["commands"])
                self.assertTrue(report["next"])
        self.assertFalse(self.task.exists())

    def test_stages_have_separate_caps_and_closed_entries_are_immutable(self):
        self.open()
        self.record(1, refs=["caller:open"])
        before = (self.task / "self-review.json").read_bytes()
        self.record(1, expected=2)
        self.assertEqual((self.task / "self-review.json").read_bytes(), before)
        self.assertEqual(self.record(2)["outcome"], "limit-reached")
        self.assertEqual(self.open(stage="code")["passes"], 0)
        self.assertEqual(self.record(1, "clean", "code")["outcome"], "clean")
        before = (self.task / "self-review.json").read_bytes()
        self.call("configure", {"candidates": [], "selections": []}, expected=2)
        self.assertEqual((self.task / "self-review.json").read_bytes(), before)
        self.call("open", {"candidates": [], "selections": []}, expected=2)
        renewed = self.open({"candidates": [], "selections": [],
                             "renewal": {"kind": "independent-revision", "ref": "review:slate-2"}})
        self.assertEqual((renewed["visit"], renewed["passes"]), (2, 0))

    def test_clean_at_cap_and_duplicate_concurrent_calls(self):
        self.open()
        with concurrent.futures.ThreadPoolExecutor(2) as executor:
            futures = [executor.submit(subprocess.run,
                        [*COMMAND, "pass", "--task-folder", str(self.task), "--stage", "spec",
                         "--json", "--input", "-"],
                        input=json.dumps({"expected_pass": 1, "result": "found", "unresolved_refs": []}),
                        text=True, capture_output=True, check=False) for _ in range(2)]
        results = [future.result() for future in futures]
        self.assertEqual(sorted(result.returncode for result in results), [0, 2])
        self.assertEqual(self.call("status")["passes"], 1)
        self.assertEqual(self.record(2, "clean")["outcome"], "clean")

    def test_project_union_missing_inventory_and_grouped_modes(self):
        config = self.project / ".bootgear/config"
        config.mkdir(parents=True)
        (config / "self-review.json").write_text(json.dumps({"candidates": [{"name": "alpha"}, {"name": "beta"}]}))
        self.assertEqual(self.call("open", {}, expected=2)["outcome"], "needs-candidates")
        result = self.call("open", {"candidates": [], "selections": []}, expected=2)
        self.assertEqual(result["outcome"], "needs-selection")
        self.assertEqual(result["pending"], ["alpha", "beta"])
        self.assertFalse((self.task / "self-review.json").exists())
        self.open({"candidates": [], "selections": [self.source("alpha", "invoke"), self.source("beta", "neither")]})
        self.assertEqual(len(self.call("status")["candidates"]), 2)

    def test_reconfiguration_preserves_snapshots_scope_and_budget(self):
        inventory = [{"name": "alpha", "origin": "user-request"}]
        self.open({"candidates": inventory, "selections": [self.source("alpha")]})
        self.record(1)
        changed = self.source("alpha", "invoke", "only wording (spec); no runtime checks")
        result = self.call("configure", {"candidates": inventory, "selections": [changed]})
        self.assertEqual(result["passes"], 1)
        self.assertEqual(result["selections"][0]["scope"], changed["scope"])
        old = result["pass_history"][0]["selections"][0]
        self.assertEqual(old["mode"], "absorb")
        before = (self.task / "self-review.json").read_bytes()
        changed.pop("confirmation")
        refused = self.call("configure", {"candidates": inventory, "selections": [changed]}, expected=2)
        self.assertIn("confirmation", refused["diagnostic"])
        self.assertEqual((self.task / "self-review.json").read_bytes(), before)

    def test_bad_structured_fields_group_errors_without_write(self):
        result = self.call("open", {"candidates": [{"name": "-bad", "origin": "invented"}],
                                   "selections": [self.source("unknown")], "limit": 4}, expected=2)
        for fragment in ("name", "origin", "unknown", "limit_confirmation"):
            self.assertIn(fragment, result["diagnostic"])
        self.assertFalse((self.task / "self-review.json").exists())

    def test_file_input_relative_gear_paths_and_settings(self):
        source = self.root / "request.json"
        source.write_text(json.dumps({"candidates": [], "selections": []}))
        env = dict(os.environ, GEAR_CALLER_CWD=str(self.root))
        result = subprocess.run([*COMMAND, "open", "--task-folder", "task", "--project-root", "project",
                                 "--stage", "spec", "--input", "request.json", "--json"],
                                text=True, capture_output=True, check=False, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["task_folder"], str(self.task))
        self.assertEqual(self.call("settings")["defaults"]["limit"], 2)

    def test_unavailable_lock_reports_real_mechanism_without_record(self):
        self.task.mkdir()
        (self.task / ".self-review.lock").mkdir()
        result = self.call("open", {"candidates": [], "selections": []}, expected=3)
        self.assertEqual(result["outcome"], "unavailable")
        self.assertIn("advisory-lock", result["diagnostic"])
        self.assertFalse((self.task / "self-review.json").exists())

    def test_process_exit_releases_lock_and_existing_lockfile_is_not_ownership(self):
        self.task.mkdir()
        code = ("import fcntl,sys; lock=open(sys.argv[1], 'a+'); "
                "fcntl.flock(lock.fileno(), fcntl.LOCK_EX); "
                "print('locked', flush=True); sys.stdin.read()")
        process = subprocess.Popen(["python3", "-c", code, str(self.task / ".self-review.lock")],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        assert process.stdout is not None
        self.assertEqual(process.stdout.readline().strip(), "locked")
        process.terminate()
        process.communicate(timeout=5)
        self.assertEqual(self.open()["passes"], 0)

    def test_budget_cannot_reset_or_increase_and_renewal_needs_evidence(self):
        self.open()
        self.record(1)
        before = (self.task / "self-review.json").read_bytes()
        self.call("open", {"candidates": [], "selections": [],
                           "renewal": {"kind": "independent-revision", "ref": "review:early"}}, expected=2)
        self.call("configure", {"candidates": [], "selections": [], "limit": 3,
                                "limit_confirmation": {"kind": "user-message", "ref": "conversation:limit"}}, expected=2)
        self.assertEqual((self.task / "self-review.json").read_bytes(), before)
        self.record(2)
        before = (self.task / "self-review.json").read_bytes()
        for renewal in ({"kind": "independent-revision"}, {"ref": "review:x"}):
            self.call("open", {"candidates": [], "selections": [], "renewal": renewal}, expected=2)
            self.assertEqual((self.task / "self-review.json").read_bytes(), before)
        result = self.open({"candidates": [], "selections": [], "limit": 3,
                            "limit_confirmation": {"kind": "user-message", "ref": "conversation:limit"},
                            "renewal": {"kind": "confirmed-intent-change", "ref": "conversation:changed",
                                        "confirmation": {"kind": "user-confirmed-ledger-entry", "ref": "ledger:choice"}}})
        self.assertEqual((result["visit"], result["limit"]), (2, 3))
        self.assertEqual(result["checkpoints"][0]["passes"], 2)

    def test_project_origins_survive_union_and_config_removal(self):
        config = self.project / ".bootgear/config"
        config.mkdir(parents=True)
        project_file = config / "self-review.json"
        project_file.write_text(json.dumps({"candidates": [{"name": "alpha"}]}))
        inventory = [{"name": "alpha", "origin": "user-request"}, {"name": "beta", "origin": "host-registration"}]
        selections = [self.source("alpha"), self.source("beta")]
        selections[1]["confirmation"] = {"kind": "user-confirmed-ledger-entry", "ref": "ledger:confirmed"}
        result = self.open({"candidates": inventory, "selections": selections})
        self.assertEqual(result["candidates"][0]["origins"], ["project-config", "user-request"])
        self.record(1)
        project_file.unlink()
        before = (self.task / "self-review.json").read_bytes()
        refused = self.call("configure", {"candidates": [], "selections": []}, expected=2)
        self.assertIn("alpha", refused["diagnostic"])
        self.assertEqual((self.task / "self-review.json").read_bytes(), before)
        result = self.call("configure", {"candidates": inventory, "selections": selections})
        self.assertIn("project-config", result["candidates"][0]["origins"])
        before = (self.task / "self-review.json").read_bytes()
        selections[0]["confirmation"] = {"kind": "deputy-advice", "ref": "deputy:advice"}
        refused = self.call("configure", {"candidates": inventory, "selections": selections}, expected=2)
        self.assertIn("confirmation.kind", refused["diagnostic"])
        self.assertEqual((self.task / "self-review.json").read_bytes(), before)

    def test_pass_validation_groups_errors_and_default_output_is_prose(self):
        self.open()
        before = (self.task / "self-review.json").read_bytes()
        refused = self.call("pass", {"expected_pass": 0, "result": "unknown", "unresolved_refs": ["-bad", ""]}, expected=2)
        for field in ("expected_pass", "result", "unresolved_refs[0]", "unresolved_refs[1]"):
            self.assertIn(field, refused["diagnostic"])
        self.assertEqual((self.task / "self-review.json").read_bytes(), before)
        env = dict(os.environ)
        env.pop("BOOTGEAR_OUTPUT", None)
        result = subprocess.run([*COMMAND, "status", "--task-folder", str(self.task)],
                                text=True, capture_output=True, check=False, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Outcome: ready", result.stdout)
        self.assertTrue(result.stdout.splitlines()[-1].startswith("Next:"))

    def test_usage_error_names_commands_example_and_next(self):
        result = subprocess.run([*COMMAND, "open"], text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn(f"Example: {PROGRAM} open --task-folder TASK --stage spec --json",
                      result.stdout + result.stderr)
        for fragment in ("Example:", "Commands:", "Next:"):
            self.assertIn(fragment, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
