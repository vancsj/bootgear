"""Ledger file: gapless seq, locking under concurrent writers, replay rejection."""
from __future__ import annotations

import fcntl
import json
import multiprocessing
import os
import subprocess
import time

from conftest import BIN, Converge


def test_seq_gapless_and_envelope(cv: Converge) -> None:
    cv.init()
    assert cv.file() == "F001"
    assert cv.file(claim="second") == "F002"
    events = cv.events()
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert [e["event"] for e in events] == ["init", "file", "file"]
    assert all(e["ts"].endswith("Z") for e in events)
    assert events[0]["as"] == "orch"
    assert events[1]["as"] == "finder"


def test_init_snapshots_angles_and_config(cv: Converge) -> None:
    cv.init()
    init = cv.events()[0]
    assert init["mode"] == "full"
    assert init["lenses"] == ["correctness", "security"]
    assert init["config"]["caps"] == {"refute_rounds": 5, "cut_rounds": 3, "per_lens": 3, "agents": 5}
    assert {"find", "attack", "evaluate", "decide"} == {a["tag"] for a in init["angles"]}


def test_init_once_and_failed_init_leaves_no_file(cv: Converge) -> None:
    err = cv.refused("init", "bad", "--as", "orch", "--mode", "full")
    assert "full mode needs at least one lens" in err
    assert not cv.path("bad").exists()
    cv.init()
    before = cv.path().read_bytes()
    err = cv.refused("init", "s1", "--as", "orch", "--mode", "full", "--lenses", "x")
    assert "already initialised" in err
    assert cv.path().read_bytes() == before


def test_invalid_write_lists_every_problem_and_writes_nothing(cv: Converge) -> None:
    cv.init()
    before = cv.path().read_bytes()
    err = cv.refused("file", "s1", "--as", "f1", "--lens", "correctness", "--angle", "nope",
                     "--loc", "no-line", "--claim", " ", "--trigger", "t", "--origin", "bogus")
    for fragment in ("unknown find angle 'nope'", "`loc` must match", "`claim` must be a non-empty",
                     "`origin` must be one of"):
        assert fragment in err
    assert cv.path().read_bytes() == before


def test_write_without_init_refused(cv: Converge) -> None:
    err = cv.refused("file", "ghost", "--as", "f1", "--loc", "a:1", "--claim", "c",
                     "--trigger", "t", "--origin", "lens")
    assert "no slate 'ghost'" in err
    assert not cv.path("ghost").exists()


def test_bad_slate_id_refused(cv: Converge) -> None:
    assert "slate id must match" in cv.refused("status", "Bad/Slate")


def _writer(dir_: str, home: str, env_extra: dict[str, str], agent: str, count: int) -> None:
    env = {**os.environ, **env_extra, "HOME": home}
    for i in range(count):
        subprocess.run([str(BIN), "file", "s1", "--dir", dir_, "--as", agent,
                        "--lens", "correctness", "--angle", "changed-contract",
                        "--loc", f"src/{agent}.py:{i + 1}", "--claim", f"{agent} claim {i}",
                        "--trigger", "t", "--origin", "lens"],
                       check=True, capture_output=True, env=env)


def test_two_concurrent_writers_lose_nothing(cv: Converge) -> None:
    cv.init()
    count = 8
    ctx = multiprocessing.get_context("spawn")
    extra = {k: v for k, v in cv.env.items() if k.startswith("UV_")}
    procs = [ctx.Process(target=_writer, args=(str(cv.dir), str(cv.home), extra, agent, count))
             for agent in ("find-a", "find-b")]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(120)
        assert proc.exitcode == 0
    events = cv.events()
    assert [e["seq"] for e in events] == list(range(1, 2 * count + 2))
    ids = [e["id"] for e in events[1:]]
    assert ids == [f"F{n:03d}" for n in range(1, 2 * count + 1)]
    by_agent = {a: sum(1 for e in events[1:] if e["as"] == a) for a in ("find-a", "find-b")}
    assert by_agent == {"find-a": count, "find-b": count}
    cv.ok("status", "s1")


def test_writer_waits_for_the_lock(cv: Converge) -> None:
    cv.init()
    fd = os.open(cv.path(), os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        proc = subprocess.Popen([str(BIN), *cv.with_dir("file", "s1"), "--as", "f1",
                                 "--lens", "correctness", "--angle", "changed-contract",
                                 "--loc", "a.py:1", "--claim", "c", "--trigger", "t",
                                 "--origin", "lens"],
                                env=cv.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(1.5)
        assert proc.poll() is None, "writer finished while another process held the lock"
        assert len(cv.path().read_text().splitlines()) == 1
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == 0, err
    assert b"FILED F001" in out


def test_hand_corrupted_line_refuses_every_command(cv: Converge) -> None:
    cv.init()
    cv.file()
    lines = cv.path().read_text().splitlines()
    event = json.loads(lines[1])
    event["loc"] = "not a loc"
    lines[1] = json.dumps(event)
    cv.path().write_text("\n".join(lines) + "\n")
    for command in ("status", "render", "coverage", "cutoff"):
        err = cv.refused(command, "s1")
        assert "ledger is corrupt" in err and "line 2" in err
    before = cv.path().read_bytes()
    assert "ledger is corrupt" in cv.refused("angle-na", "s1", "--as", "x", "--phase", "find",
                                              "--angle", "failure-path", "--lens", "security",
                                              "--reason", "r")
    assert cv.path().read_bytes() == before


def test_out_of_order_and_truncated_lines_refused(cv: Converge) -> None:
    cv.init()
    cv.file()
    cv.file(claim="two")
    lines = cv.path().read_text().splitlines()
    swapped = [lines[0], lines[2], lines[1]]
    cv.path().write_text("\n".join(swapped) + "\n")
    assert "seq must be 2" in cv.refused("status", "s1")
    cv.path().write_text("\n".join(lines))  # last line lacks its newline
    assert "truncated" in cv.refused("status", "s1")
    cv.path().write_text("\n".join(lines) + "\n{not json\n")
    assert "not valid JSON" in cv.refused("status", "s1")


def test_wrapper_needs_uv_on_path(cv: Converge) -> None:
    result = subprocess.run(["/bin/sh", str(BIN), "angles"], capture_output=True, text=True,
                            env={"PATH": "/usr/bin:/bin", "HOME": str(cv.home)}, check=False)
    assert result.returncode == 127
    assert "uv is required" in result.stderr
