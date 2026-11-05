"""Execute the documented direct calls with isolated target CLIs."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REFERENCE = Path(__file__).resolve().parents[1] / "skills/advisor/references/direct.md"


@pytest.mark.parametrize("target", ("codex", "claude"))
@pytest.mark.parametrize("overrides", ((), ("MODEL",), ("EFFORT",), ("MODEL", "EFFORT")))
def test_direct_call_keeps_defaults_or_passes_only_requested_overrides(
    target: str, overrides: tuple[str, ...], tmp_path: Path,
) -> None:
    result, recorded = run_example(target, tmp_path, overrides=overrides)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "peer final answer\n"
    assert result.stderr == ""
    args = recorded["args"]
    assert recorded["stdin"] == ""
    assert recorded["target"] == target
    scratch = Path(recorded["scratch"])
    assert scratch != tmp_path and not scratch.exists()
    if target == "claude":
        for flag in ("-p", "--safe-mode", "--no-session-persistence"):
            assert flag in args
        assert args[args.index("--tools") + 1] == ""
        assert args[args.index("--output-format") + 1] == "text"
        assert "--bare" not in args
        assert ("--model" in args) == ("MODEL" in overrides)
        assert ("--effort" in args) == ("EFFORT" in overrides)
        if "MODEL" in overrides:
            assert args[args.index("--model") + 1] == "chosen-model"
        if "EFFORT" in overrides:
            assert args[args.index("--effort") + 1] == "high"
    else:
        assert args[0] == "exec"
        assert "--ephemeral" in args
        assert args[args.index("-s") + 1] == "read-only"
        assert "--ignore-user-config" in args and "--ignore-rules" in args
        assert not Path(args[args.index("-o") + 1]).exists()
        assert ("-m" in args) == ("MODEL" in overrides)
        assert ("-c" in args) == ("EFFORT" in overrides)
        if "MODEL" in overrides:
            assert args[args.index("-m") + 1] == "chosen-model"
        if "EFFORT" in overrides:
            assert args[args.index("-c") + 1] == 'model_reasoning_effort="high"'


@pytest.mark.parametrize("target", ("codex", "claude"))
def test_direct_failure_preserves_status_and_diagnostic(target: str, tmp_path: Path) -> None:
    result, recorded = run_example(target, tmp_path, failure=True)
    assert result.returncode == 7
    assert result.stdout == ""
    if target == "codex":
        diagnostic = Path(result.stderr.strip().split("Read diagnostic log: ", 1)[1])
        try:
            assert "target diagnostic" in diagnostic.read_text()
            assert "target failure result" in diagnostic.read_text()
            assert diagnostic.stat().st_mode & 0o777 == 0o600
        finally:
            diagnostic.unlink()
    else:
        assert "target diagnostic" in result.stderr
        assert "target failure result" in result.stderr
    assert not Path(recorded["scratch"]).exists()


def test_failed_codex_does_not_publish_prompt_or_reasoning(tmp_path: Path) -> None:
    result, _ = run_example("codex", tmp_path, failure=True)
    assert result.returncode == 7
    assert "private prompt echo" not in result.stderr
    assert "private reasoning" not in result.stderr
    diagnostic = Path(result.stderr.strip().split("Read diagnostic log: ", 1)[1])
    diagnostic.unlink()


def run_example(target: str, tmp_path: Path, *, overrides: tuple[str, ...] = (),
                failure: bool = False) -> tuple[subprocess.CompletedProcess[str], dict]:
    examples = re.findall(r"```bash\n(.*?)\n```", REFERENCE.read_text(), re.DOTALL)
    script = examples[0 if target == "codex" else 1]
    executable = tmp_path / target
    capture = tmp_path / "capture.json"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "target = pathlib.Path(sys.argv[0]).name\n"
        "scratch = args[args.index('-C') + 1] if target == 'codex' else os.getcwd()\n"
        "pathlib.Path(os.environ['DIRECT_CAPTURE']).write_text(json.dumps(\n"
        "    dict(target=target, args=args, scratch=scratch, stdin=sys.stdin.read())))\n"
        "if os.environ['DIRECT_FAILURE'] == '1':\n"
        "    if target == 'codex':\n"
        "        print('private prompt echo')\n"
        "        print('private reasoning', file=sys.stderr)\n"
        "    print('target failure result')\n"
        "    print('target diagnostic', file=sys.stderr)\n"
        "    sys.exit(7)\n"
        "if target == 'codex':\n"
        "    pathlib.Path(args[args.index('-o') + 1]).write_text('peer final answer\\n')\n"
        "    print('streamed banner')\n"
        "else:\n"
        "    print('peer final answer')\n"
        "print('startup notice', file=sys.stderr)\n"
    )
    executable.chmod(0o755)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("BOOTGEAR_ADVISOR_")}
    env.update(PATH=f"{tmp_path}{os.pathsep}{env['PATH']}", DIRECT_CAPTURE=str(capture),
               DIRECT_FAILURE="1" if failure else "0")
    # Set the other host's overrides too; they must not reach this target.
    for host in ("CODEX", "CLAUDE"):
        for kind in ("MODEL", "EFFORT"):
            if host.lower() != target or kind in overrides:
                env[f"BOOTGEAR_ADVISOR_{host}_{kind}"] = "chosen-model" if kind == "MODEL" else "high"
    result = subprocess.run(["bash", "-c", script], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=10, check=False)
    return result, json.loads(capture.read_text())
