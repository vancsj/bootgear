"""Pins the constants the skill body states in prose, so prose and code cannot drift."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from . import model, store
from .constants import BROKEN_EVIDENCE, HASH_LEN, OUTPUT_RE
from .model import _detect_mainline, answer_hash, band, confidence, ref_state
from .scoring import cut_candidates, match_score, mint_slug, normalize
from .store import Entry, _flush_restamp, index_entries, read_cache


def cmd_selftest(args, root):
    """Pins the confidence anchors and band edges the skill body states in prose.

    Every `confidence()` argument here is a count of INDEPENDENT verifiers. The
    author's own ✓ is deliberately absent from it: they wrote the Evidence line,
    so their agreement with it corroborates nothing.
    """
    checks = [
        ("author's ✓ only — nothing independent yet", confidence(0, 0), 0.30),
        ("2 independent ✓ + 1 ✗ (skill example)", confidence(2, 1), 0.63),
        ("all sigs voided by an edit", confidence(0, 0), 0.30),
        ("one independent ✓", confidence(1, 0), 0.61),
        ("two independent ✓", confidence(2, 0), 0.79),
        ("6 ✓ outweigh 1 ✗ — dissent votes, never vetoes", confidence(6, 1), 0.78),
        # 1.00 is a human's `Asserted:` ruling. Uncapped this returns exactly
        # 1.00, and a counted tally prints it too.
        ("agreement stops below 1.00 — that value is asserted, never counted",
         confidence(9, 0), 0.99),
        ("and stays there however many agree", confidence(40, 0), 0.99),
    ]
    # A band edge with no test is an edge free to drift: raising the top one above
    # 0.80 would silently make a single ✗ an absolute veto, since conf can never
    # exceed DISPUTE_PENALTY ** no however many verifiers agree.
    bands = [
        ("author's ✓ only reads unconfirmed", band(confidence(0, 0)), "unconfirmed"),
        ("one independent ✓ reads confirmed", band(confidence(1, 0)), "confirmed"),
        ("two independent ✓ read well-confirmed", band(confidence(2, 0)), "well-confirmed"),
        ("a lone ✗ cannot veto the top band", band(confidence(9, 1)), "well-confirmed"),
    ]
    bad = 0
    for label, got, want in checks:
        ok = abs(got - want) < 0.005
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {got:.2f} (want {want:.2f})  {label}")
    for label, got, want in bands:
        ok = got == want
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {got:<14} (want {want})  {label}")
    h = answer_hash("pnpm for all installs", "Because: x")
    ok = len(h) == HASH_LEN and re.fullmatch(r"[0-9a-f]+", h)
    bad += not ok
    print(f"{'ok  ' if ok else 'FAIL'}  h={h}  sha256 of claim+Because(+Ref), first {HASH_LEN} hex")

    # Appending a check must not move the hash, or a zoom-out costs every vote.
    from .model import Answer
    probe = Answer("a1", "pnpm for all installs", 0.30, "2026-01-01", False, 0)
    probe.because = "Because: x"
    probe.evidences = ["Evidence: y"]
    one = probe.hash
    probe.evidences = ["Evidence: y", "Evidence: z"]
    two = probe.hash
    ok = one == two == h
    bad += not ok
    print(f"{'ok  ' if ok else 'FAIL'}  {two}=={one}  appending a check keeps standing sigs")

    # Repo must stay out too. If it ever joins, `set-repo` silently voids every
    # signature on the answer it touches.
    probe.repo = "Repo: some-checkout"
    ok = probe.hash == h
    bad += not ok
    print(f"{'ok  ' if ok else 'FAIL'}  {probe.hash}=={h}  a Repo: line does not touch the hash")

    # Claim and Ref must still void — they are what a signature asserts.
    edited = answer_hash("bun for all installs", "Because: x")
    reffed = answer_hash("pnpm for all installs", "Because: x", "Ref: origin/feature/x")
    for label, got in [("editing the claim still voids every sig", edited != h),
                       ("a Ref: still voids — a branch claim is a different claim",
                        reffed != h)]:
        bad += not got
        print(f"{'ok  ' if got else 'FAIL'}  {got!s:<5}  (want True)   {label}")

    # A slug is a filename someone reads for years, and stemming one mangles it:
    # `spring` becomes `spr`, `corpus` becomes `corpu`. Matching still stems, so the
    # two must not share a code path.
    naming = [("which caching library version", "caching-library-version"),
              ("index build cache corpus size", "index-build-cache-corpus")]
    for text, want in naming:
        got = mint_slug(text)
        ok = got == want
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {got:<22} (want {want})  slug minted unstemmed")
    stems = normalize("which caching library version")
    ok = "cach" in stems
    bad += not ok
    print(f"{'ok  ' if ok else 'FAIL'}  {' '.join(stems):<22} matching still stems")

    # A perfect score has to mean the whole question was accounted for. The
    # damping is what stops a five-word query reaching 1.00 against an unrelated
    # entry just because two of its common words were the only ones any entry
    # contained.
    class _E:
        def __init__(self, toks): self._t = set(toks)
        def tokens(self): return self._t
    pool = [_E(["one", "two", "three", "four"]), _E(["one", "two", "five"])]
    partial = match_score({"one", "two", "x1", "x2", "x3"}, pool[0].tokens(), pool)
    full = match_score({"one", "two"}, pool[0].tokens(), pool)
    for label, got, want in [("2 of 5 query terms judgeable damps below 0.45", partial, 0.40),
                             ("every term judgeable and matched scores 1.00", full, 1.00)]:
        ok = abs(got - want) < 0.005
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {got:.2f} (want {want:.2f})  {label}")

    # The cut is where a reader stops reading, so its shape is pinned here.
    gap = [(1.00, "a"), (0.95, "b"), (0.31, "c"), (0.29, "d"), (0.28, "e")]
    cuts = [("cuts at the largest drop, not a constant", len(cut_candidates(gap)), 2),
            ("min_keep leaves a runner-up to compare", len(cut_candidates(
                [(1.00, "a"), (0.20, "b"), (0.19, "c")])), 2),
            ("a list at or under min_keep is untouched", len(cut_candidates(
                [(1.00, "a"), (0.90, "b")])), 2)]
    for label, got, want in cuts:
        ok = got == want
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {got} kept (want {want})  {label}")

    for label, text, should_flag in [
            ("a 'file not found' line is refused", "error: file not found: /tmp/x.txt", True),
            ("a 'fatal:' git line is refused", "fatal: not a git repository", True),
            ("ordinary grep output is accepted", "src/widget.py:12: def bar():", False)]:
        got = bool(BROKEN_EVIDENCE.search(text))
        ok = got == should_flag
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {got!s:<5}  (want {should_flag})  {label}")

    # The mainline ref is DISCOVERED, never assumed. A hardcoded `origin/master`
    # would make every landed branch read `live` forever on a `main` repo, and
    # fail silently: a ref that resolves to nothing is indistinguishable from a
    # branch that has not merged. Pinned on a real repo because the behaviour
    # depends on what git actually answers, which no unit-level stub captures.
    with tempfile.TemporaryDirectory() as td:
        r = Path(td)

        def _g(*a):
            return subprocess.run(["git", "-C", str(r), *a], capture_output=True)

        subprocess.run(["git", "init", "-q", "-b", "main", str(r)], capture_output=True)
        _g("config", "user.email", "t@t")
        _g("config", "user.name", "t")
        (r / "a.txt").write_text("x", encoding="utf-8")
        _g("add", "a.txt")
        _g("commit", "-qm", "init")
        _g("checkout", "-q", "-b", "feature/x")
        (r / "b.txt").write_text("y", encoding="utf-8")
        _g("add", "b.txt")
        _g("commit", "-qm", "feat")
        _g("checkout", "-q", "main")
        _g("merge", "-q", "--no-ff", "feature/x", "-m", "merge")
        # Stand in for a clone: `origin/*` is what an Evidence line and a ref
        # claim actually name.
        _g("update-ref", "refs/remotes/origin/main", "refs/heads/main")
        _g("update-ref", "refs/remotes/origin/feature/x", "refs/heads/feature/x")

        # `_detect_mainline` is asked directly: it consults only git, so the pin
        # cannot be perturbed by whatever `ref:` the running machine has configured.
        detected = _detect_mainline(r)

        cwd, prev = os.getcwd(), os.environ.get("LEDGER_REF")
        try:
            os.chdir(r)
            model._MAINLINE_CACHE.clear()
            os.environ["LEDGER_REF"] = "origin/main"    # env must win over config
            merged_state = ref_state("feature/x")
        finally:
            os.chdir(cwd)
            if prev is None:
                os.environ.pop("LEDGER_REF", None)
            else:
                os.environ["LEDGER_REF"] = prev
            model._MAINLINE_CACHE.clear()
    for label, got, want in [
            ("a main-default repo resolves its own mainline", detected, "origin/main"),
            ("a branch merged into main reads merged, not live", merged_state, "merged")]:
        ok = got == want
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {got!s:<14} (want {want})  {label}")

    # A signature's recorded output lives under it in the entry, and the next
    # signature must land after that block. `last_body_idx` only advances on lines
    # the parser recognises, and output lines match nothing, so appending there
    # would splice a signature into the middle of the previous one's output —
    # where SIG_RE would still find it and the tally would still count it.
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td)
        (probe / "tech").mkdir()
        f = probe / "tech" / "sigs.md"
        f.write_text("# tech/sigs\nQ: Do signatures survive an output block?\n\n"
                     "## a1 · yes                          conf 0.30 · checked 2026-01-01\n"
                     "Because: pinned here.\nEvidence: echo x\n"
                     "    ✓ aaaa 2026-01-01  h=000000  (author)\n"
                     "    ✗ bbbb 2026-01-02  h=000000\n"
                     "    > cat: nope: No such file or directory\n"
                     "    > exit 1\n", encoding="utf-8")
        e = Entry(f, probe)
        a = e.answers[0]
        attached = a.sigs[-1]["output"]
        e.lines[a.last_line_idx + 1:a.last_line_idx + 1] = ["    ✓ cccc 2026-01-03  h=000000"]
        e.write()
        store.reset_restamp()
        after = Entry(f, probe)
        tail = after.answers[0]
    for label, got, want in [
            ("output attaches to the signature above it", len(attached), 2),
            ("a later signature lands after the output block", tail.sigs[-1]["who"], "cccc"),
            ("and every signature is still counted", len(tail.sigs), 3),
            ("the output block is not read as a signature", len(tail.sigs[1]["output"]), 2)]:
        ok = got == want
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {got!s:<14} (want {want})  {label}")

    # Correcting your own vote rewrites your line and its output block, and must
    # leave every other signature where it was. The span is computed from the
    # target's own recorded output, so an off-by-one either strands a `>` block
    # under someone else's ✓ — where it reads as their evidence — or eats the
    # signature below it, silently dropping a vote from the tally.
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td)
        (probe / "tech").mkdir()
        f = probe / "tech" / "own.md"
        f.write_text("# tech/own\nQ: Can a session correct its own vote in place?\n\n"
                     "## a1 · yes                          conf 0.30 · checked 2026-01-01\n"
                     "Because: pinned here.\nEvidence: echo x\n"
                     "    ✗ aaaa 2026-01-01  h=000000  e=1  (author)\n"
                     "    > it failed\n"
                     "    > on two lines\n"
                     "    ✓ bbbb 2026-01-02  h=000000  e=1\n", encoding="utf-8")
        e = Entry(f, probe)
        a = e.answers[0]
        target = a.sigs[0]
        span = slice(target["idx"], target["idx"] + 1 + len(target["output"]))
        e.lines[span] = ["    ✓ aaaa 2026-01-03  h=000000  e=1  (author)"]
        e.write()
        store.reset_restamp()
        fixed = Entry(f, probe).answers[0]
    for label, got, want in [
            ("correcting a vote leaves one line per signer", len(fixed.sigs), 2),
            ("the corrected mark replaces the old one", fixed.sigs[0]["mark"], "✓"),
            ("its stale output block goes with it", len(fixed.sigs[0]["output"]), 0),
            ("authorship survives the correction", fixed.sigs[0]["author"], True),
            ("another signer's vote is untouched", fixed.sigs[1]["who"], "bbbb")]:
        ok = got == want
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {got!s:<14} (want {want})  {label}")

    # A `>` line belongs to the nearest signature above it, which is ownership and
    # not adjacency: on a hand-mangled answer something can sit between the two.
    # Pinned because counting the parser's attached output instead of the run
    # actually under the line deletes whatever is in the gap — here, a check.
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td)
        (probe / "tech").mkdir()
        f = probe / "tech" / "gap.md"
        f.write_text("# tech/gap\nQ: Is recorded output always adjacent to its signature?\n\n"
                     "## a1 · no                           conf 0.30 · checked 2026-01-01\n"
                     "Because: pinned here.\nEvidence: echo x\n"
                     "    ✗ aaaa 2026-01-01  h=000000  e=1  (author)\n"
                     "Evidence: echo y\n"
                     "    > stranded failure\n", encoding="utf-8")
        gap = Entry(f, probe).answers[0]
        target = gap.sigs[0]
        adjacent = 0
        idx = target["idx"] + 1
        while idx < len(gap_lines := Entry(f, probe).lines) and OUTPUT_RE.match(gap_lines[idx]):
            adjacent += 1
            idx += 1
    for label, got, want in [
            ("output can attach across a gap", len(target["output"]), 1),
            ("but the run under the line is empty", adjacent, 0),
            ("so counting attached output would overrun", len(target["output"]) != adjacent, True)]:
        ok = got == want
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {got!s:<14} (want {want})  {label}")

    # These go through cmd_sign, not through e.lines: the pins above would all pass
    # while `--as` quietly rewrote someone else's vote, because they never exercise
    # the signer-resolution path that decides whose line gets replaced.
    with tempfile.TemporaryDirectory() as td:
        shared_root, local_root = Path(td) / "shared", Path(td) / "local"
        for r in (shared_root, local_root):
            (r / "tech").mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(r)], check=True)
        f = local_root / "tech" / "asif.md"
        # A real claim body, so the hash the tool computes is the one the signatures
        # carry: a placeholder h= would void them and take the correction path away.
        f.write_text("# tech/asif\nQ: Can --as overwrite another session's vote?\n\n"
                     "## a1 · no                           conf 0.49 · checked 2024-01-06\n"
                     "Because: pinned here.\nEvidence: echo x\n", encoding="utf-8")
        real_hash = Entry(f, local_root).answers[0].hash
        f.write_text(f.read_text(encoding="utf-8")
                     + f"    ✓ mine 2024-01-06  h={real_hash}  e=1  (author)\n"
                     + f"    ✗ dave 2024-01-07  h={real_hash}  e=1\n"
                     + "    > dave's counter-example\n", encoding="utf-8")
        env = dict(os.environ, CLAUDE_CODE_SESSION_ID="mine-0000-0000",
                   LEDGER_ROOT=str(shared_root), LEDGER_LOCAL_ROOT=str(local_root))
        def run_sign(*extra: str) -> tuple[int, str]:
            p = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parents[1] / "ledger.py"),
                 "sign", "tech/asif", "a1", *extra],
                capture_output=True, text=True, env=env)
            return p.returncode, (p.stdout + p.stderr)
        impersonate_rc, impersonate_out = run_sign("--as", "dave")
        after_impersonate = f.read_text(encoding="utf-8")
        legacy_rc, _ = run_sign()
    for label, got, want in [
            ("--as cannot correct another session's vote", impersonate_rc != 0, True),
            ("and says whose signature it is", "not yours to correct" in impersonate_out, True),
            ("dave's ✗ survives the attempt", "✗ dave" in after_impersonate, True),
            ("so does the output recorded under it",
             "dave's counter-example" in after_impersonate, True),
            ("a no-op re-sign is refused", legacy_rc != 0, True)]:
        ok = got == want
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {got!s:<14} (want {want})  {label}")

    # Cache validity across a write. Both halves fail silently — a lost re-stamp
    # only shows up as a slow `resolve`, and a lost invalidation as a resolver
    # confidently missing an entry that exists — so they are pinned, not trusted.
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td)
        (probe / "tech").mkdir()
        f = probe / "tech" / "x.md"
        f.write_text("# tech/x\nQ: Does the cache survive a write?\n\n"
                     "## a1 · yes                          conf 0.30 · checked 2026-01-01\n"
                     "Because: pinned here.\nEvidence: echo x\n", encoding="utf-8")
        index_entries(probe)
        store.reset_restamp()
        e = Entry(f, probe)
        e.lines.append("    ✓ zz 2026-01-01  h=000000")
        e.write()                      # a signature: mtime moves, identity does not
        _flush_restamp()
        survives = read_cache(probe) is not None
        f.write_text(f.read_text() + "\n", encoding="utf-8")   # unannounced edit
        rebuilds = read_cache(probe) is None
        store.reset_restamp()

        # A rename must survive the exit re-stamp. Without this, a `git mv` during
        # a folder split leaves the next command re-stamping the old rows as
        # current, and `resolve` serves slugs whose files no longer exist with a
        # stamp that matches the tree exactly. Nothing else reports it.
        index_entries(probe)
        store.reset_restamp()
        f.rename(probe / "tech" / "renamed.md")
        store.restamp_cache(probe)
        _flush_restamp()
        rename_rebuilds = read_cache(probe) is None
        store.reset_restamp()
    for label, got in [("a signature leaves the cache valid — no rebuild", survives),
                       ("an unannounced edit still invalidates it", rebuilds),
                       ("a rename is never laundered by the exit re-stamp", rename_rebuilds)]:
        bad += not got
        print(f"{'ok  ' if got else 'FAIL'}  {got!s:<5}  (want True)   {label}")

    print(f"\n{'all anchors hold' if not bad else str(bad) + ' FAILED'}")
    return 1 if bad else 0
