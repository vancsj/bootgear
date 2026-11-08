"""Compare shared plugin code and the engine modules with explicit host adaptations."""

import ast
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_DIR.parents[1]
CLAUDE_ENGINE = REPO_ROOT / "plugins" / "engine"
CLAUDE_CONVERGE = REPO_ROOT / "plugins" / "converge"


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


# Each pair is exact Claude and Codex text. Shared source must match outside these blocks.
ENGINE_ADAPTATIONS: dict[str, list[tuple[str, str]]] = {
    "config.py": [
        (
            '    host_dir = (".codex" if os.environ.get("BOOTGEAR_HOST") == "codex" else ".claude")',
            '    host_dir = (".claude" if os.environ.get("BOOTGEAR_HOST") == "claude" else ".codex")',
        ),
    ],
    "session.py": [
        (
            '',
            '    recall            print the settlement and recovery state together',
        ),
        (
            '',
            (
                '    s = sub.add_parser("recall", parents=[dir_parent],\n'
                '                        help="print settlement, full decisions, open todos, state, "\n'
                '                             "and recent pitches")\n'
                '    s.add_argument("run_id", nargs="?")\n'
                '    s.set_defaults(func=_run_id_command(cmd_recall))'
            ),
        ),
    ],
    "state.py": [
        (
            'no reminder: work toward /goal',
            'no reminder: work toward goal',
        ),
        (
            "before entering '{dest}': confirm /goal's {dest}",
            "before entering '{dest}': confirm goal's {dest}",
        ),
    ],
}
CODEX_ONLY_SESSION_FUNCTIONS = frozenset({"_recall_section", "cmd_recall"})


class BundleDriftTest(unittest.TestCase):
    def assertEngineSourcesMatch(self, name: str, claude: str, codex: str) -> None:
        normalized = []
        for host, source in (("claude", claude), ("codex", codex)):
            for claude_block, codex_block in ENGINE_ADAPTATIONS[name]:
                expected = claude_block if host == "claude" else codex_block
                if expected:
                    self.assertEqual(source.count(expected), 1,
                                     f"{name}: stale {host} adaptation: {expected!r}")
                else:
                    self.assertNotIn(codex_block, source,
                                     f"{name}: Codex-only block appeared in Claude source")
                if host == "codex":
                    source = source.replace(codex_block, claude_block, 1)
            if name == "session.py":
                nodes = [node for node in ast.parse(source).body
                         if isinstance(node, ast.FunctionDef)
                         and node.name in CODEX_ONLY_SESSION_FUNCTIONS]
                for function in CODEX_ONLY_SESSION_FUNCTIONS:
                    self.assertEqual(sum(node.name == function for node in nodes),
                                     1 if host == "codex" else 0,
                                     f"{host}: unexpected host-only function count for {function}")
                omitted: set[int] = set()
                for node in nodes:
                    if node.end_lineno is None:
                        self.fail(f"{host}: missing source span for {node.name}")
                    omitted.update(range(node.lineno, node.end_lineno + 1))
                source = "\n".join(line for index, line in enumerate(source.splitlines(), 1)
                                   if index not in omitted)
            normalized.append([line for line in source.splitlines() if line.strip()])
        self.assertEqual(normalized[1], normalized[0], f"shared engine source differs: {name}")

    def engineSources(self, name: str) -> tuple[str, str]:
        return ((CLAUDE_ENGINE / "src/engine" / name).read_text(),
                (PLUGIN_DIR / "src/engine" / name).read_text())

    def test_engine_modules_match_outside_host_adaptations(self):
        for name in ENGINE_ADAPTATIONS:
            with self.subTest(name=name):
                self.assertEngineSourcesMatch(name, *self.engineSources(name))

    def test_engine_guard_rejects_shared_code_added_on_either_host(self):
        for name in ENGINE_ADAPTATIONS:
            for host in (0, 1):
                with self.subTest(name=name, host=host):
                    sources = list(self.engineSources(name))
                    sources[host] += "\ndef unexpected_shared_helper():\n    return None\n"
                    with self.assertRaises(self.failureException):
                        self.assertEngineSourcesMatch(name, *sources)

    def test_engine_guard_rejects_stale_adaptation_blocks(self):
        for name, adaptations in ENGINE_ADAPTATIONS.items():
            for index, pair in enumerate(adaptations):
                for host, block in enumerate(pair):
                    if not block:
                        continue
                    with self.subTest(name=name, adaptation=index, host=host):
                        sources = list(self.engineSources(name))
                        sources[host] = sources[host].replace(block, "", 1)
                        with self.assertRaises(self.failureException):
                            self.assertEngineSourcesMatch(name, *sources)

    def test_engine_guard_rejects_repeated_config_adaptation(self):
        for host, block in enumerate(ENGINE_ADAPTATIONS["config.py"][0]):
            with self.subTest(host=host):
                sources = list(self.engineSources("config.py"))
                sources[host] = sources[host].replace(block, block + "\n" + block, 1)
                with self.assertRaises(self.failureException):
                    self.assertEngineSourcesMatch("config.py", *sources)

    def test_engine_guard_requires_each_codex_only_function_once(self):
        for function in CODEX_ONLY_SESSION_FUNCTIONS:
            for copies in (0, 2):
                with self.subTest(function=function, copies=copies):
                    claude, codex = self.engineSources("session.py")
                    node = next(node for node in ast.parse(codex).body
                                if isinstance(node, ast.FunctionDef) and node.name == function)
                    lines = codex.splitlines(keepends=True)
                    block = "".join(lines[node.lineno - 1:node.end_lineno])
                    changed = codex.replace(block, block * copies, 1)
                    with self.assertRaises(self.failureException):
                        self.assertEngineSourcesMatch("session.py", claude, changed)


    def test_host_context_hook_matches_claude_source(self):
        self.assertSameBytes(
            CLAUDE_ENGINE / "hooks" / "pre_tool_use_task_identity.py",
            PLUGIN_DIR / "hooks" / "pre_tool_use_task_identity.py",
        )

    def assertSameTree(self, source: Path, copy: Path):
        expected, actual = _files(source), _files(copy)
        self.assertTrue(expected, f"{source} is empty or missing")
        self.assertEqual(sorted(actual), sorted(expected), f"file set of {copy}")
        changed = [name for name in expected if actual[name] != expected[name]]
        self.assertEqual(changed, [], f"bytes differ from {source}")

    def assertSameBytes(self, source: Path, copy: Path):
        self.assertEqual(copy.read_bytes(), source.read_bytes(), f"{copy} differs from {source}")

    def test_author_helpers_match_claude_source(self):
        for plugin, package, command in (("review", "self_review", "self-review"),
                                          ("spec", "spec_feedback", "spec-feedback")):
            with self.subTest(package=package):
                source = REPO_ROOT / "plugins" / plugin
                claude_files = _files(source / "src" / package)
                codex_files = _files(PLUGIN_DIR / "src" / package)
                self.assertEqual(sorted(codex_files), sorted(claude_files))
                codex_source = codex_files["cli.py"].decode()
                claude_source = claude_files["cli.py"].decode()
                claude_route = f'current_program("{plugin}", "{command}")'
                codex_route = f'current_program("engine", "{command}")'
                self.assertEqual(codex_source.count(codex_route), 1)
                codex_source = codex_source.replace(codex_route, claude_route, 1)
                self.assertEqual(codex_source, claude_source, f"{package}/cli.py differs")
                for name in claude_files.keys() - {"cli.py"}:
                    self.assertEqual(codex_files[name], claude_files[name], f"{package}/{name} differs")
                self.assertIn(f"[commands.{command}]", (source / "gear.toml").read_text())
                self.assertIn(f"[commands.{command}]", (PLUGIN_DIR / "gear.toml").read_text())

    def test_self_review_skill_and_cases_match(self):
        source = REPO_ROOT / "plugins" / "review"
        claude_skill = (source / "skills/self-review/SKILL.md").read_text()
        codex_skill = (PLUGIN_DIR / "skills/self-review/SKILL.md").read_text()
        codex_fallback = "If `cli:gear` is missing, install `cli@bootgear` with `codex plugin add cli@bootgear`."
        claude_fallback = ("If `cli:gear` is missing on Claude Code, run `/plugin install cli@bootgear`. "
                           "On Codex, run `codex plugin add cli@bootgear`.")
        self.assertEqual(codex_skill.replace(codex_fallback, claude_fallback, 1), claude_skill)
        claude_cases = (source / "tests/test_self_review.py").read_text()
        codex_cases = (PLUGIN_DIR / "tests/test_self_review.py").read_text()
        def test_methods(text: str) -> dict[str, str]:
            tree = ast.parse(text)
            cls = next(node for node in tree.body
                       if isinstance(node, ast.ClassDef) and node.name == "SelfReviewTest")
            return {node.name: ast.get_source_segment(text, node) or ""
                    for node in cls.body if isinstance(node, ast.FunctionDef)
                    and node.name.startswith("test_")}

        claude_methods, codex_methods = test_methods(claude_cases), test_methods(codex_cases)
        self.assertEqual(claude_methods.keys(), codex_methods.keys())
        usage = "test_usage_error_names_commands_example_and_next"
        for name in claude_methods.keys() - {usage}:
            self.assertEqual(claude_methods[name], codex_methods[name], name)
        for source_text in (claude_methods[usage], codex_methods[usage]):
            for fragment in ("Example:", "Commands:", "Next:"):
                self.assertIn(fragment, source_text)
        self.assertIn('PROGRAM = display("engine", "self-review")', codex_cases)
        self.assertIn("Example: {PROGRAM} open --task-folder TASK", codex_methods[usage])

    def test_converge_package_matches_claude_source(self):
        claude_root = CLAUDE_CONVERGE / "src" / "converge"
        codex_root = PLUGIN_DIR / "src" / "converge"
        claude_files, codex_files = _files(claude_root), _files(codex_root)
        self.assertEqual(sorted(codex_files), sorted(claude_files))
        for name, claude_source in claude_files.items():
            codex_source = codex_files[name]
            if name in {"cli.py", "ledger.py", "protocol.py"}:
                codex_text = codex_source.decode()
                if name in {"ledger.py", "protocol.py"}:
                    codex_route = 'current_program("engine", "converge")'
                    claude_route = 'current_program("converge", "converge")'
                    self.assertEqual(codex_text.count(codex_route), 1)
                    codex_text = codex_text.replace(codex_route, claude_route, 1)
                if name == "cli.py":
                    for codex_route, claude_route in (
                        ('current_program("engine", "converge")',
                         'current_program("converge", "converge")'),
                        ('gear_command("engine", "converge")',
                         'gear_command("converge", "converge")'),
                    ):
                        self.assertEqual(codex_text.count(codex_route), 1)
                        codex_text = codex_text.replace(codex_route, claude_route, 1)
                codex_source = codex_text.encode()
            self.assertEqual(codex_source, claude_source, f"{name} differs")

    def test_converge_fresh_eye_instructions_match_across_hosts(self):
        claude_skill = CLAUDE_CONVERGE / "skills" / "converge" / "SKILL.md"
        codex_skill = PLUGIN_DIR / "skills" / "converge" / "SKILL.md"
        claude_lines = [line for line in claude_skill.read_text().splitlines()
                        if "Fresh-eye batch (`batch` `fresh-eye`)" in line]
        codex_lines = [line for line in codex_skill.read_text().splitlines()
                       if "Fresh-eye batch (`batch` `fresh-eye`)" in line]
        self.assertEqual(len(claude_lines), 1)
        self.assertEqual(codex_lines, claude_lines)
        self.assertIn("including names outside the fixed list", claude_lines[0])
        self.assertIn("fixed list is not a menu", claude_lines[0])
        self.assertIn("For example", claude_lines[0])

    def test_clikit_has_one_shared_source(self):
        source = REPO_ROOT / "plugins" / "cli" / "src" / "bootgear_cli" / "clikit.py"
        copies = (
            REPO_ROOT / "plugins" / "engine" / "src" / "engine" / "clikit.py",
            PLUGIN_DIR / "src" / "engine" / "clikit.py",
            CLAUDE_CONVERGE / "src" / "converge" / "clikit.py",
            PLUGIN_DIR / "src" / "converge" / "clikit.py",
            REPO_ROOT / "plugins" / "memory-ledger" / "scripts" / "ledgerlib" / "clikit.py",
        )
        self.assertTrue(source.is_file())
        self.assertEqual([], [str(path) for path in copies if path.exists()])

    def test_seats_copies_match_engine_source(self):
        # Settlement validation and converge init check seats with one rule set.
        source = CLAUDE_ENGINE / "src" / "engine" / "seats.py"
        for copy in (
            PLUGIN_DIR / "src" / "engine" / "seats.py",
            CLAUDE_CONVERGE / "src" / "converge" / "seats.py",
        ):
            self.assertSameBytes(source, copy)

    def test_host_adapter_core_matches_claude_source(self):
        for name in ("host_adapter.py", "host_contracts.py", "policy.py"):
            self.assertSameBytes(
                CLAUDE_ENGINE / "src" / "engine" / name,
                PLUGIN_DIR / "src" / "engine" / name,
            )


if __name__ == "__main__":
    unittest.main()
