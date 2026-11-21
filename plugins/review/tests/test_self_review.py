import json
import os
import subprocess
import unittest

from self_review_test_support import COMMAND, SelfReviewTestCase


class SelfReviewTest(SelfReviewTestCase):
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


if __name__ == "__main__":
    unittest.main()
