"""`init --snapshot/--pass/--since` pin a temp-index work-tree commit; `prune` drops refs."""
from __future__ import annotations

import json
import subprocess

from conftest import Converge

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def git(cv: Converge, *args: str, check: bool = True) -> str:
    out = subprocess.run(["git", "-C", str(cv.project), "-c", "user.name=t",
                          "-c", "user.email=t@example.com", *args],
                         capture_output=True, text=True, env=cv.env, check=False)
    if check:
        assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def repo(cv: Converge, commit: bool = True) -> None:
    git(cv, "init", "-q")
    if commit:
        (cv.project / "a.py").write_text("x = 1\n")
        git(cv, "add", "a.py")
        git(cv, "commit", "-q", "-m", "base")


def init_args(cv: Converge, slate: str, *extra: str) -> list[str]:
    return ["init", slate, "--dir", str(cv.dir), "--as", "orch", "--mode", "full",
            "--lenses", "correctness", "--project-root", str(cv.project),
            "--angles", str(cv.angles), *extra]


def ref(cv: Converge, slate: str) -> str | None:
    out = git(cv, "rev-parse", "--verify", "--quiet", f"refs/converge/{slate}", check=False)
    return out or None


def pinned(cv: Converge, slate: str) -> str:
    sha = ref(cv, slate)
    assert sha is not None, f"refs/converge/{slate} is missing"
    return sha


def init_event(cv: Converge, slate: str) -> dict:
    return json.loads(cv.path(slate).read_text().splitlines()[0])


def test_snapshot_captures_untracked_without_touching_index(cv: Converge) -> None:
    repo(cv)
    git(cv, "checkout", "-q", "--detach")
    (cv.project / "new.py").write_text("y = 2\n")
    (cv.project / "a.py").write_text("x = 3\n")
    index = cv.project / ".git" / "index"
    status = git(cv, "status", "--porcelain")  # refreshes the index's stat data first
    before = index.read_bytes()
    head = git(cv, "rev-parse", "HEAD")
    out = cv(*init_args(cv, "s1", "--snapshot", "--pass", "1")).stdout
    sha = pinned(cv, "s1")
    assert f"pass=1 snapshot={sha}" in out
    assert index.read_bytes() == before
    assert git(cv, "status", "--porcelain") == status
    assert git(cv, "rev-parse", "HEAD") == head
    assert git(cv, "rev-parse", f"{sha}^") == head
    assert git(cv, "show", f"{sha}:new.py") == "y = 2"
    assert git(cv, "show", f"{sha}:a.py") == "x = 3"
    event = init_event(cv, "s1")
    assert (event["snapshot"], event["pass"]) == (sha, 1)
    assert "since" not in event
    assert git(cv, "log", "-1", "--format=%an <%ae>", sha) == "converge <converge@localhost>"


def test_snapshot_on_unborn_head_is_empty_tree_without_parent(cv: Converge) -> None:
    repo(cv, commit=False)
    cv(*init_args(cv, "s1", "--snapshot", "--pass", "1"))
    sha = pinned(cv, "s1")
    assert git(cv, "rev-parse", f"{sha}^{{tree}}") == EMPTY_TREE
    assert git(cv, "rev-list", "--parents", "-n", "1", sha) == sha


def test_pin_failure_refuses_before_any_event(cv: Converge) -> None:
    repo(cv)
    # A valid slate id that is not a valid ref name, so update-ref fails.
    err = cv(*init_args(cv, "bad..id", "--snapshot", "--pass", "1"), code=2).stderr
    assert "pin: git update-ref refs/converge/bad..id" in err
    assert not cv.path("bad..id").exists()


def test_append_failure_removes_the_ref(cv: Converge) -> None:
    repo(cv)
    args = init_args(cv, "s1", "--snapshot", "--pass", "1")
    args[args.index("correctness")] = "Not_A_Lens"
    err = cv(*args, code=2).stderr
    assert "`lenses` must be a list of ids" in err
    assert "removed refs/converge/s1" in err
    assert ref(cv, "s1") is None
    assert not cv.path("s1").exists()


def test_append_failure_reports_a_ref_it_could_not_remove(cv: Converge, tmp_path) -> None:
    repo(cv)
    real = subprocess.run(["which", "git"], capture_output=True, text=True, check=True).stdout.strip()
    wrap = tmp_path / "bin"
    wrap.mkdir()
    (wrap / "git").write_text(
        f'#!/bin/sh\ncase " $* " in *" update-ref -d "*) exit 1;; esac\nexec "{real}" "$@"\n')
    (wrap / "git").chmod(0o755)
    cv.env["PATH"] = f"{wrap}:{cv.env['PATH']}"
    args = init_args(cv, "s1", "--snapshot", "--pass", "1")
    args[args.index("correctness")] = "Not_A_Lens"
    err = cv(*args, code=2).stderr
    assert "removed refs/converge/s1" not in err
    assert "remove refs/converge/s1 failed (exit 1)" in err
    assert f"converge prune s1 --project-root {cv.project}" in err
    assert ref(cv, "s1") is not None


def test_retry_overwrites_an_orphan_ref(cv: Converge) -> None:
    repo(cv)
    head = git(cv, "rev-parse", "HEAD")
    git(cv, "update-ref", "refs/converge/s1", head)
    cv(*init_args(cv, "s1", "--snapshot", "--pass", "1"))
    assert ref(cv, "s1") == init_event(cv, "s1")["snapshot"] != head


def test_snapshot_refuses_without_git_or_pass(cv: Converge) -> None:
    err = cv(*init_args(cv, "s1", "--snapshot", "--since", "s0"), code=2).stderr
    assert "--snapshot requires --pass <n>" in err
    assert "--snapshot requires a git --project-root" in err
    err = cv(*init_args(cv, "s1", "--pass", "2", "--since", "s0"), code=2).stderr
    assert "--since requires --snapshot" in err
    assert not cv.path("s1").exists()


def test_snapshot_refuses_an_initialised_slate_and_keeps_its_ref(cv: Converge) -> None:
    repo(cv)
    cv(*init_args(cv, "s1", "--snapshot", "--pass", "1"))
    sha = ref(cv, "s1")
    err = cv(*init_args(cv, "s1", "--snapshot", "--pass", "1"), code=2).stderr
    assert "slate 's1' is already initialised" in err
    assert ref(cv, "s1") == sha


def test_since_prints_the_delta_and_uses_the_rereview_cutoff(cv: Converge) -> None:
    repo(cv)
    cv(*init_args(cv, "s1", "--snapshot", "--pass", "1"))
    (cv.project / "a.py").write_text("x = 4\n")
    out = cv(*init_args(cv, "s2", "--snapshot", "--pass", "2", "--since", "s1")).stdout
    prev, this = pinned(cv, "s1"), pinned(cv, "s2")
    assert f"DIFF since s1: git diff {prev} {this}" in out
    event = init_event(cv, "s2")
    assert event["since"] == {"slate": "s1", "snapshot": prev}
    assert event["config"]["cutoff"]["report_if"][2]["severity"] == [
        "security", "data-loss", "wrong-behavior"]
    render = cv.ok("render", "s2").stdout
    assert f"pass: 2 · snapshot: {this}" in render
    assert f"delta since `s1`: `git diff {prev} {this}`" in render
    assert "a.py" in git(cv, "diff", "--stat", prev, this)


def test_since_refusals_name_the_failed_check(cv: Converge) -> None:
    repo(cv)
    err = cv(*init_args(cv, "s2", "--snapshot", "--pass", "2", "--since", "s1"), code=2).stderr
    assert "--since: prev exists: no slate 's1'" in err

    cv(*init_args(cv, "plain"))
    err = cv(*init_args(cv, "s2", "--snapshot", "--pass", "2", "--since", "plain"),
             code=2).stderr
    assert "--since: prev has a snapshot sha: 'plain' was not started with --snapshot" in err

    cv(*init_args(cv, "s1", "--snapshot", "--pass", "1"))
    err = cv(*init_args(cv, "s2", "--snapshot", "--pass", "3", "--since", "s1"), code=2).stderr
    assert "--since: --pass must equal 's1''s pass + 1 (2); got 3" in err

    fake = "0" * 40
    path = cv.path("s1")
    event = json.loads(path.read_text())
    path.write_text(json.dumps({**event, "snapshot": fake}) + "\n")
    err = cv(*init_args(cv, "s2", "--snapshot", "--pass", "2", "--since", "s1"), code=2).stderr
    assert f"--since: git cat-file -e {fake}^{{commit}} failed" in err
    assert not cv.path("s2").exists() and ref(cv, "s2") is None


def test_prune_removes_exactly_the_named_refs(cv: Converge) -> None:
    repo(cv)
    head = git(cv, "rev-parse", "HEAD")
    for slate in ("slate-1", "slate-2", "slate-10", "other"):
        git(cv, "update-ref", f"refs/converge/{slate}", head)
    out = cv("prune", "slate-1", "slate-2", "slate-9",
             "--project-root", str(cv.project)).stdout
    assert out.splitlines() == ["PRUNED refs/converge/slate-1",
                                "PRUNED refs/converge/slate-2",
                                "WARN no ref refs/converge/slate-9"]
    left = git(cv, "for-each-ref", "--format=%(refname)", "refs/converge/").splitlines()
    assert left == ["refs/converge/other", "refs/converge/slate-10"]


def test_prune_refuses_bad_ids_before_deleting(cv: Converge) -> None:
    repo(cv)
    git(cv, "update-ref", "refs/converge/s1", git(cv, "rev-parse", "HEAD"))
    err = cv("prune", "s1", "Bad/Id", "--project-root", str(cv.project), code=2).stderr
    assert "slate id must match" in err and "'Bad/Id'" in err
    assert ref(cv, "s1") is not None


def test_prune_refuses_outside_git(cv: Converge) -> None:
    err = cv("prune", "s1", "--project-root", str(cv.project), code=2).stderr
    assert "is not a git work tree" in err
