"""The commands that add to an entry: new, rival, sign, refute, promote.

Nothing here rewrites an answer body. An answer id is immutable and gets
referenced by number from other answers, so a body that could change would
make every such reference a pointer at something that has since moved. A
wrong or unportable check is corrected by adding an answer that carries the
fixed one — `--keep-evidence` brings across the checks that still hold.
"""
from __future__ import annotations

import os
import sys
from datetime import date

from .config import LOCAL, SHARED, Ledger, locate, pick, resolve_you
from .constants import (
    FALLBACK_REF,
    MAINLINE_CANDIDATES,
    OUTPUT_PREFIX,
    OUTPUT_RE,
    SEED_CONF,
    SIBLING_MAX_EVIDENCE,
)
from .gates import (
    check_claim,
    check_not_asked,
    portability_problem,
    refuse_problems,
    report_evidence,
)
from .lint import warn_missing_about
from .model import (
    Answer,
    asserted_line,
    author_sig,
    band,
    confidence,
    git_user,
    mainline_ref,
    ref_state,
    render_header,
    repo_name,
    sig_line,
    split_evidence,
)
from .rules import warn_missing_rules
from .store import Entry, add_cache_row, find_entry

PORTABILITY = "hardcoded personal path"


def _as_list(v):
    """argparse `append` gives a list; a bare string is still accepted."""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def output_lines(output: str | None, note: str | None = None) -> list[str]:
    """What a run printed, attached under the signature that recorded it.

    In the entry rather than a sibling `.debate.md`, so an entry is one file: a
    debate file is named from the entry's path, so moving the entry would strand
    it and the next ✗ would open a second one at the new path.

    Blockquoted, never fenced. A `>` prefix puts a non-matching character where
    SIG_RE and ANSWER_RE need `✓`/`✗` or `#`, so output containing something that
    looks like a signature or an answer header cannot be parsed as one.
    """
    body = (output or "(no output captured)").rstrip().splitlines() or ["(no output captured)"]
    if note:
        body = [note, ""] + body
    return [(OUTPUT_PREFIX + ln).rstrip() for ln in body]


def target_ledger(args) -> Ledger:
    """Which ledger a new entry goes into. No default, on purpose.

    Defaulting either way is wrong in a way the author cannot see afterwards.
    Default to shared and a machine-local fact reaches the team's history, which
    is append-only and so cannot be taken back. Default to local and a finding
    the team needed sits in a repo with no remote, invisible, until someone
    re-derives it. Requiring the flag makes the choice happen once, out loud, at
    the only moment anyone still knows which kind of fact this is.
    """
    ledgers = args.ledgers
    if len(ledgers) == 1:
        return ledgers[0]
    if args.shared == args.local:          # both set, or neither
        sys.exit("say which ledger: --shared (the team can read it, forever) or --local "
                 "(this machine only). Shared is append-only — ask the human before "
                 "filing anything machine-specific, path-specific or personal there.")
    return pick(ledgers, SHARED if args.shared else LOCAL,
                getattr(args, "context", None))


def _scope_lines(args) -> tuple[str | None, str | None]:
    """The optional `Repo:` and `Ref:` lines for an answer being written.

    `--repo` is filled in from the current checkout whenever `--ref` was given
    and `--repo` was not, because a bare branch name is exactly the ambiguity
    `Repo:` exists to close: `feature/x` resolves in whichever repo the reader
    stands in, and where it resolves nowhere `lint` says to delete the entry.
    Without a `--ref` nothing is inferred — a question that is not about a
    codebase has no repo, and a guess is worse than an absence.
    """
    repo = getattr(args, "repo", None)
    context = getattr(args, "context", None)
    if not repo and args.ref:
        repo = repo_name(context=context)
        if repo:
            print(f"REPO     inferred {repo} from the current checkout — pass --repo to "
                  f"override; a bare ref resolves in whatever repo the reader is in")
    return (f"Repo: {repo}" if repo else None,
            f"Ref: {args.ref}" if args.ref else None)


def cmd_set_repo(args, root):
    """Name the checkout an existing answer's checks run in.

    The one command that edits an answer in place, and it is only safe because
    `Repo:` is outside the hash: no signature is voided, so nothing has to be
    re-verified. It exists because every answer in the ledger predates the field,
    and hand-editing entry files is the thing the skill tells you never to do.
    """
    e = find_entry(root, args.slug)
    a = _get_answer(e, args.answer)
    before = a.hash
    line = f"Repo: {args.repo}"
    if a.repo:
        idx = e.lines.index(a.repo, a.header_idx)
        was = a.repo_value
        e.lines[idx] = line
        note = f"{was} → {args.repo}"
    else:
        # Ahead of Ref: when there is one, so scope reads repo-then-ref; after
        # the Evidence lines either way.
        anchor = e.lines.index(a.ref, a.header_idx) if a.ref else a.last_body_idx + 1
        e.lines.insert(anchor, line)
        note = f"set to {args.repo}"
    e.write()
    e = find_entry(root, args.slug)
    a = _get_answer(e, args.answer)
    if a.hash != before:
        sys.exit(f"BUG: writing Repo: changed the hash {before} → {a.hash}. Repo must stay "
                 f"out of the hash or every signature on this answer is voided.")
    yes, no, void = a.tally()
    print(f"{e.slug} {a.aid}  Repo: {note}   {yes}✓/{no}✗ intact, {void} voided "
          f"(unchanged), h={a.hash}")


def _body_end(a) -> int:
    """The last line of an answer's body, before its first signature.

    Not `last_body_idx`, which advances on signature lines too — inserting there
    puts a body line after the votes, or inside a recorded output block.
    """
    return a.sigs[0]["idx"] - 1 if a.sigs else a.last_line_idx


def cmd_assert(args, root):
    """Pin an answer at 1.00 on a human's ruling, or hand it back to the tally.

    For a question no check can settle — an intent, a decision, a system that no
    longer exists to be queried.

    It suspends the tally's hold on the header and nothing else: signatures keep
    accumulating, `show` prints what they count, and `lint` reports a standing ✗
    as ASSERTED-CONTESTED.

    `Asserted:` is outside the answer hash, so applying or lifting it voids no
    signature.
    """
    e = find_entry(root, args.slug)
    a = _get_answer(e, args.answer)
    before = a.hash
    yes, no, _ = a.tally()
    counted = confidence(a.independent(), no)

    if args.clear:
        if not a.asserted:
            sys.exit(f"{e.slug} {a.aid} is not asserted — nothing to clear")
        if a.asserted_line:
            e.lines.remove(a.asserted_line)
        a.asserted = False
        # header_idx is unmoved: the Asserted: line always sits below it.
        e.lines[a.header_idx] = render_header(a, counted, str(date.today()))
        e.write()
        print(f"{e.slug} {a.aid}  assertion cleared — back to the tally at "
              f"conf {counted:.2f} [{band(counted)}]   {yes}✓/{no}✗, "
              f"{a.independent()} independent")
        return

    problems = []
    if not args.why:
        problems.append(("missing --why",
                         ("--why is required: an assertion is a human ruling, and a ruling "
                          "with no reason recorded is indistinguishable from a hand-edited "
                          "number")))
    who = args.by or git_user()
    if not who:
        problems.append(("missing name", ("no name for the assertion: `git config user.name` "
                                          "is unset — pass --by")))
    refuse_problems(f"assert {e.slug} {a.aid}", problems)
    if a.asserted and a.asserted_line:
        sys.exit(f"{e.slug} {a.aid} is already asserted:\n  {a.asserted_line}\n"
                 f"Clear it first (`--clear`) if the ruling has changed.")
    if no:
        print(f"WARN     {no}✗ standing on this answer; the tally counts {counted:.2f}. "
              f"Asserting does not answer them — they stay visible and `lint` will "
              f"report ASSERTED-CONTESTED until they are dealt with.")

    line = asserted_line(who, args.why)
    if a.asserted_line:                       # a hand-written header, no record
        e.lines[e.lines.index(a.asserted_line)] = line
    else:
        # Below the header, so header_idx still addresses the line to re-render.
        e.lines.insert(_body_end(a) + 1, line)
    a.asserted = True
    e.lines[a.header_idx] = render_header(a, 1.00, str(date.today()))
    e.write()

    e = find_entry(root, args.slug)
    a = _get_answer(e, args.answer)
    if a.hash != before:
        sys.exit(f"BUG: writing Asserted: changed the hash {before} → {a.hash}. It must stay "
                 f"out of the hash or every signature on this answer is voided.")
    print(f"{e.slug} {a.aid}  conf 1.00 [asserted] by {who}   {yes}✓/{no}✗ intact, "
          f"tally counts {counted:.2f}, h={a.hash}")
    print(f"     {line}")
    print("     the tally keeps running underneath; `assert --clear` hands the header back "
          "to it.")


def cmd_add_evidence(args, root):
    """Append a check to an existing answer. Voids no signature.

    Append only — it refuses a duplicate and never edits or removes a line; `lint`
    enforces the same against what is committed.
    """
    e = find_entry(root, args.slug)
    a = _get_answer(e, args.answer)
    before, was = a.hash, len(a.evidences)
    if before is None:
        sys.exit(f"{e.slug} {a.aid}: no Because:/Evidence: — seed those first")
    new = [f"Evidence: {ev}" for ev in _as_list(args.evidence)]
    kind = locate(args.ledgers, args.slug).kind
    problems = [("duplicate check", f"{e.slug} {a.aid} already carries that check: {ln}")
                for ln in new if ln in a.evidences]
    if port := portability_problem(args.evidence, kind, args.force):
        problems.append((PORTABILITY, port))
    refuse_problems(f"add-evidence {e.slug} {a.aid}", problems)
    report_evidence(args.evidence, root, kind, getattr(args, "context", None))
    anchor = e.lines.index(a.evidences[-1], a.header_idx)
    e.lines[anchor + 1:anchor + 1] = new
    e.write()

    e = find_entry(root, args.slug)
    a = _get_answer(e, args.answer)
    if a.hash != before:
        sys.exit(f"BUG: appending a check changed the hash {before} → {a.hash}. Evidence "
                 f"must stay out of the hash or every signature here is voided.")
    yes, no, void = a.tally()
    print(f"{e.slug} {a.aid}  checks {was} → {len(a.evidences)}   {yes}✓/{no}✗ intact, "
          f"{void} voided (unchanged), h={a.hash}")
    print("     standing signatures carry the depth they verified at; a new signature "
          "records the full set.")


def cmd_new(args, root):
    lg = target_ledger(args)
    root = lg.root
    path = (root / args.slug).with_suffix(".md")
    if path.exists():
        sys.exit(f"exists: {path} — sign it or add a rival answer instead")
    # Every gate before any Evidence line runs: each can take up to 180 s, and a
    # refusal after them would cost the writer all of it again on the re-run.
    problems = []
    if restated := check_not_asked(args.q, args.slug, args.ledgers, args.anyway):
        problems.append(("restates an existing question", restated))
    if long_claim := check_claim(args.claim, args.force):
        problems.append(("claim too long", long_claim))
    if port := portability_problem(args.evidence, lg.kind, args.force):
        problems.append((PORTABILITY, port))
    refuse_problems(f"new {args.slug}", problems)
    report_evidence(args.evidence, root, lg.kind, getattr(args, "context", None))
    path.parent.mkdir(parents=True, exist_ok=True)
    a = Answer("a1", args.claim, SEED_CONF, str(date.today()), False, 0)
    a.because = f"Because: {args.because}"
    a.evidences = [f"Evidence: {ev}" for ev in _as_list(args.evidence)]
    context = getattr(args, "context", None)
    you = resolve_you(args.as_, context)
    a.repo, a.ref = _scope_lines(args)
    conf = confidence(0, 0)
    body = [f"# {args.slug}", f"Q: {args.q}"]
    if args.alt_terms:
        body.append(f"alt_terms: {args.alt_terms}")
    body += ["", render_header(a, conf, str(date.today())), a.because, *a.evidences]
    body += [ln for ln in (a.repo, a.ref) if ln]
    body += [author_sig(you, a.hash, len(a.evidences)), ""]
    path.write_text("\n".join(body), encoding="utf-8")
    add_cache_row(root, args.slug, args.q,
                  [t.strip() for t in (args.alt_terms or "").split(",") if t.strip()])
    print(f"seeded {path}  [{lg.kind}]  conf {conf:.2f} [{band(conf)}]  ✓ {you} (author)"
          f" — 0 independent yet   [{a.scope_label}]")
    if a.ref_value and ref_state(a.ref_value, a.repo_value, context) == "live":
        print(f"WARN     {a.ref_value} is unmerged — when it lands, `lint` flags this entry "
              f"to be promoted and re-verified against "
              f"{mainline_ref(context=context) or FALLBACK_REF}")
    warn_missing_about(root, path)
    warn_missing_rules(root, lg.kind, getattr(args, "prog", "ledger.py"))


def _get_answer(e: Entry, aid: str) -> Answer:
    for a in e.answers:
        if a.aid == aid:
            return a
    sys.exit(f"{e.slug} has no {aid} (has: {', '.join(x.aid for x in e.answers)})")


def show_siblings(e: Entry) -> None:
    """Put the answers already on this question in front of whoever is adding one.

    `new` runs the resolver; `rival` shows the siblings so an answer is not
    added without its author seeing what it answers alongside. Otherwise
    near-identical claims accumulate and a correction ends up not saying what
    it corrects.

    Nothing is refused here. Whether a new answer contradicts, refines or merely
    restates is a judgement about meaning, and a token score over claims that
    answer the same question by construction cannot make it.
    """
    if not e.answers:
        return
    print(f"EXISTING answers on {e.slug} — say in your `Because:` how yours differs:")
    for a0 in e.answers:
        yes, no, _ = a0.tally()
        conf0 = 1.00 if a0.asserted else confidence(a0.independent(), no)
        print(f"   {a0.aid} · conf {conf0:.2f} [{band(conf0)}] · {yes}✓/{no}✗, "
              f"{a0.independent()} independent")
        print(f"      {a0.claim}")
        for ev in a0.evidences[:SIBLING_MAX_EVIDENCE]:
            print(f"      {ev}")
        if len(a0.evidences) > SIBLING_MAX_EVIDENCE:
            print(f"      … {len(a0.evidences) - SIBLING_MAX_EVIDENCE} more check(s) — "
                  f"`ledger.py show {e.slug}`")
    print("   → keep the checks you still agree with: --keep-evidence <aN>")
    print("   → the claim stays one falsifiable sentence; the disagreement goes in Because:")


def cmd_rival(args, root):
    you = resolve_you(args.as_, getattr(args, "context", None))
    e = find_entry(root, args.slug)
    show_siblings(e)
    kind = locate(args.ledgers, args.slug).kind
    problems = []
    if long_claim := check_claim(args.claim, args.force):
        problems.append(("claim too long", long_claim))
    if port := portability_problem(args.evidence, kind, args.force):
        problems.append((PORTABILITY, port))
    refuse_problems(f"rival {e.slug}", problems)
    report_evidence(args.evidence, root, kind, getattr(args, "context", None))
    # max+1, never count+1. An answer id is immutable and gets referenced by
    # number from other answers, so a reused id makes one reference point at two
    # different bodies — and `_get_answer` returns the first match, so a `sign`
    # would land on whichever came first. Counting reuses an id after any gap.
    used = [int(x.aid[1:]) for x in e.answers if x.aid[1:].isdigit()]
    aid = f"a{max(used, default=0) + 1}"
    a = Answer(aid, args.claim, SEED_CONF, str(date.today()), False, 0)
    a.because = f"Because: {args.because}"
    # Checks carried over from an answer this one disagrees with, ahead of the
    # new one. A correction usually leaves most of the old ground standing, and
    # re-typing those lines by hand is how they drift into near-copies that hash
    # differently for no reason. Kept first, so the file reads as "what still
    # holds, then what overturns it"; order is part of the hash.
    inherited: list[str] = []
    for aid0 in _as_list(getattr(args, "keep_evidence", None)):
        for ev in _get_answer(e, aid0).evidences:
            if ev not in inherited:
                inherited.append(ev)
    a.evidences = inherited + [f"Evidence: {ev}" for ev in _as_list(args.evidence)
                               if f"Evidence: {ev}" not in inherited]
    a.repo, a.ref = _scope_lines(args)
    conf = confidence(0, 0)
    e.lines += [render_header(a, conf, str(date.today())), a.because, *a.evidences]
    e.lines += [ln for ln in (a.repo, a.ref) if ln]
    e.lines += [author_sig(you, a.hash, len(a.evidences)), ""]
    e.write()
    print(f"added {aid} to {e.slug}  conf {conf:.2f} [{band(conf)}]  ✓ {you} (author)"
          f" — 0 independent yet   [{a.scope_label}]")


def cmd_hash(args, root):
    a = _get_answer(find_entry(root, args.slug), args.answer)
    if a.hash is None:
        sys.exit(f"{args.slug} {args.answer}: missing Because:/Evidence: — not verifiable")
    print(a.hash)



def cmd_sign(args, root):
    context = getattr(args, "context", None)
    you = resolve_you(args.as_, context)
    e = find_entry(root, args.slug)
    a = _get_answer(e, args.answer)
    h = a.hash
    if h is None:
        sys.exit(f"{e.slug} {a.aid}: no runnable Evidence: — don't sign, add a rival with one")
    standing = next((s for s in a.sigs if s["who"] == you and s["hash"] == h), None)
    # Correcting a vote rewrites a line, so it is self-only. `resolve_you` returns
    # `--as` verbatim, which without this would let any caller overwrite any signer's
    # mark and delete the output recorded under it — the exact strike `refute` refuses
    # to grant. No live session id means nothing to prove ownership against, so the
    # in-place path is closed there too.
    from .identity import live_identity
    live = live_identity(context)
    if standing is not None and you != live:
        sys.exit(f"{you}'s signature on {a.aid} is not yours to correct — sign as yourself, "
                 f"or answer it with `refute {args.slug} {a.aid} {you}`")

    mark = "✗" if args.fail else "✓"
    # Editing an answer voids its author's own ✓, so the author is expected to re-sign
    # the corrected body. That re-signature has to stay marked: without this the author
    # is promoted to their own independent verifier and conf claims corroboration that
    # never happened. Authorship is a property of the session, not of one hash.
    mine = "  (author)" if any(s["who"] == you and s["author"] for s in a.sigs) else ""
    block = [sig_line(mark, you, h, len(a.evidences), author=bool(mine))]
    if args.fail:
        block += output_lines(args.output)
    if standing is None:
        e.lines[a.last_line_idx + 1:a.last_line_idx + 1] = block
    else:
        # Correcting your own standing vote rewrites that line instead of adding one.
        # Appending would read as two sessions disagreeing, and a session that has
        # changed its mind otherwise has no route at all: refute is barred against
        # your own signature, and a rival leaves the disowned mark counting here.
        # The parser attaches a `>` line to the nearest signature above it, which is
        # ownership, not adjacency: on a mangled answer a line can sit between the two.
        # So the span is the contiguous run actually under the signature, and a
        # disagreement with what the parser attached is a malformed answer — refused
        # rather than guessed, since guessing here deletes a line that is not ours.
        run = standing["idx"] + 1
        while run < len(e.lines) and OUTPUT_RE.match(e.lines[run]):
            run += 1
        if run - standing["idx"] - 1 != len(standing["output"]):
            sys.exit(f"{e.slug} {a.aid}: {you}'s recorded output is not contiguous with its "
                     f"signature — fix the answer's layout by hand before re-signing")
        # `depth` is None on a signature written before `e=` existed, and `None == 2` never matches, so treating it as unknown-and-
        # therefore-equal is what stops those lines being re-signed for the date alone.
        same_depth = standing["depth"] in (None, len(a.evidences))
        if (standing["mark"] == mark and same_depth
                and e.lines[standing["idx"] + 1:run] == block[1:]):
            sys.exit(f"session {you} already signed {a.aid} {mark} at h={h} over "
                     f"{len(a.evidences)} check(s) — nothing to correct")
        e.lines[standing["idx"]:run] = block
    e.write()

    e = find_entry(root, args.slug)
    a = _get_answer(e, args.answer)
    yes, no, _ = a.tally()
    conf = confidence(a.independent(), no)
    # A pinned header is the human's; a vote joins the tally without rewriting it.
    # `checked` advances only on a new vote or a flipped one. `sign` never runs the
    # checks, so a correction that leaves the verdict alone must not be able to
    # present an old pass as freshly verified.
    if not a.asserted:
        moved = standing is None or standing["mark"] != mark
        e.lines[a.header_idx] = render_header(
            a, conf, str(date.today()) if moved else a.checked)
        e.write()
    verb = "→" if standing is None else f"corrects its own {standing['mark']} of {standing['date']} →"
    print(f"{mark} {you} {verb} {e.slug} {a.aid}   conf {a.conf:.2f} → {conf:.2f}  [{band(conf)}]"
          f"  {yes}✓/{no}✗, {a.independent()} independent"
          + ("  SPLIT — the Evidence line is not reproducible"
             if split_evidence(yes, no) else ""))
    if standing is not None and standing["depth"] != len(a.evidences):
        print(f"     depth {standing['depth']} → {len(a.evidences)} checks; "
              f"one session, still one vote")

    if args.fail:
        print(f"failing output recorded under the signature in {e.path.name}")


def cmd_refute(args, root):
    """Answer a standing signature: re-run the same body, record the contradiction.

    It never strikes the other session's vote — vote-striking is exactly the veto
    the tally refuses to grant. It casts your own opposing vote and records the
    contradicting output under it, so a disagreement is legible rather than only
    numeric.
    """
    you = resolve_you(args.as_, getattr(args, "context", None))
    e = find_entry(root, args.slug)
    a = _get_answer(e, args.answer)
    h = a.hash
    if h is None:
        sys.exit(f"{e.slug} {a.aid}: no runnable Evidence: — nothing to answer")
    target = next((s for s in a.sigs if s["who"] == args.sig), None)
    if target is None:
        signers = ", ".join(s["who"] for s in a.sigs) or "none"
        sys.exit(f"{e.slug} {a.aid} has no signature from {args.sig} (signers: {signers})")
    if target["hash"] != h:
        sys.exit(f"{args.sig}'s signature is already void — the body changed since it was "
                 f"cast. Nothing is standing to answer; just sign.")
    if target["who"] == you:
        sys.exit("a session cannot answer its own signature — re-run and sign, or seed a rival")

    mark = "✓" if target["mark"] == "✗" else "✗"
    for sig in a.sigs:
        if sig["who"] == you and sig["hash"] == h:
            sys.exit(f"session {you} already signed {a.aid} at h={h} — one session, one vote")

    block = [sig_line(mark, you, h, len(a.evidences))]
    block += output_lines(args.output,
                          f"answers {target['who']}'s {target['mark']} of {target['date']} "
                          f"— re-ran the same body and got the opposite result.")
    e.lines[a.last_line_idx + 1:a.last_line_idx + 1] = block
    e.write()

    e = find_entry(root, args.slug)
    a = _get_answer(e, args.answer)
    yes, no, _ = a.tally()
    conf = confidence(a.independent(), no)
    # A pinned header is the human's; a vote joins the tally without rewriting it.
    if not a.asserted:
        e.lines[a.header_idx] = render_header(a, conf, str(date.today()))
        e.write()
    print(f"{mark} {you} answers {target['who']}'s {target['mark']} → {e.slug} {a.aid}   "
          f"conf {conf:.2f}  [{band(conf)}]  ({yes}✓/{no}✗, {a.independent()} independent)")
    print(f"reply recorded under your signature — {target['who']}'s vote still stands, "
          f"as it must")


def cmd_promote(args, root):
    """Re-scope a branch claim onto mainline by adding an answer, not editing one.

    Rewriting the `Ref:` line in place would be body mutation of exactly the
    kind an immutable answer forbids: the branch answer's signatures would name a
    body that no longer exists anywhere, destroying the record of who verified
    what against the branch.

    So promotion appends. The branch answer stays as written and keeps every
    signature it earned — those sessions did verify it, against the branch, and
    that stays true. The new answer says the same words about mainline, which is
    a different claim: the merge could have rebased, resolved conflicts or
    absorbed review changes. It starts at the seed conf and wins its own votes.
    """
    context = getattr(args, "context", None)
    you = resolve_you(args.as_, context)
    e = find_entry(root, args.slug)
    a = _get_answer(e, args.answer)
    # `--to` defaults to whatever THIS repo calls mainline, discovered rather
    # than assumed. Without a repo to ask, promotion has no target it can name
    # honestly, so it says so instead of writing one repo's convention into
    # another repo's ledger.
    to = args.to or mainline_ref(context=context)
    if not to:
        sys.exit("cannot tell what this repo calls mainline (no origin/HEAD and no "
                 f"{', '.join(MAINLINE_CANDIDATES)}) — pass --to explicitly, or set "
                 "`ref:` in the config / $LEDGER_REF.")
    if not a.ref_value:
        sys.exit(f"{e.slug} {a.aid} is not scoped to a ref — nothing to promote")
    if a.ref_value == to:
        sys.exit(f"{e.slug} {a.aid} is already scoped to {to}")
    for other in e.answers:
        if other.ref_value == to and other.claim == a.claim:
            sys.exit(f"{e.slug} {other.aid} already says this about {to} "
                     f"(conf {other.conf:.2f}) — sign that instead")
    problems = []
    state = ref_state(a.ref_value, a.repo_value, context)
    if state == "live" and not args.force:
        problems.append(("ref not merged",
                         (f"{a.ref_value} is not yet in {to} — the claim is still "
                          f"branch-only. Use --force only if you know better than ancestry.")))
    if state == "unknown" and not args.force:
        # `unknown` means this process cannot see the repo's refs, or cannot tell
        # what its mainline is, so the merge check did not run. Proceeding would
        # let a promotion from the wrong checkout skip the one guard that
        # establishes the branch actually landed — silently, because nothing failed.
        where = f"{a.repo_value} " if a.repo_value else ""
        problems.append(("ref state unknown",
                         (f"cannot see {where}refs from here, so whether {a.ref_value} landed "
                          f"in {to} is unverified. Run this from that checkout, or --force.")))

    # A check that names the source ref cannot be carried across. Re-running it
    # was supposed to catch this, but it does not: a merged branch still exists,
    # so `git show origin/feature/x:…` keeps passing and the new answer would
    # claim something about mainline while reading the branch. Nothing fails, so
    # nothing warns — which is exactly why it is refused here instead.
    naming = [ev for ev in a.evidences if a.ref_value in ev]
    if naming:
        problems.append(("check names the source ref",
                         f"{a.aid}'s check names {a.ref_value} outright, so promoting it "
                         f"would assert something about {to} while still reading the "
                         f"branch:\n" + "\n".join(f"  {ev}" for ev in naming)
                         + f"\nWrite a rival with a check against {to} instead."))
    checks = [ev.removeprefix("Evidence:").strip() for ev in a.evidences]
    kind = locate(args.ledgers, args.slug).kind
    if port := portability_problem(checks, kind, args.force):
        problems.append((PORTABILITY, port))
    refuse_problems(f"promote {e.slug} {a.aid}", problems)
    report_evidence(checks, root, kind, context)

    used = [int(x.aid[1:]) for x in e.answers if x.aid[1:].isdigit()]
    aid = f"a{max(used, default=0) + 1}"
    n = Answer(aid, a.claim, SEED_CONF, str(date.today()), False, 0)
    n.because = a.because
    n.evidences = list(a.evidences)
    # Promotion changes which ref the claim is about; it never moves the claim to
    # a different checkout, so `Repo:` carries across untouched.
    n.repo = a.repo
    n.ref = f"Ref: {to}"
    conf = confidence(0, 0)
    e.lines += [render_header(n, conf, str(date.today())), n.because, *n.evidences,
                *[ln for ln in (n.repo, n.ref) if ln], author_sig(you, n.hash, len(n.evidences)), ""]
    e.write()
    print(f"promoted {e.slug} {a.aid} ({a.ref_value}) → {aid} ({to})  "
          f"conf {conf:.2f} [{band(conf)}]  ✓ {you} (author)")
    print(f"{a.aid} is unchanged and keeps its {len(a.sigs)} signature(s) — they verified "
          f"it against {a.ref_value}, which is still true. {aid} starts unconfirmed: "
          f"nobody has yet run the check against {to}.")
