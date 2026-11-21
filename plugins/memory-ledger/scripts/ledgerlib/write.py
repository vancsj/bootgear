"""The commands that add to an entry: new, rival, sign, refute, promote.

Nothing here rewrites an answer body. An answer id is immutable and gets
referenced by number from other answers, so a body that could change would
make every such reference a pointer at something that has since moved. A
wrong or unportable check is corrected by adding an answer that carries the
fixed one — `--keep-evidence` brings across the checks that still hold.
"""
from __future__ import annotations

import argparse
import sys

from bootgear_cli.clikit import current_program

from .config import DEPUTY, LOCAL, SHARED, Ledger, locate, pick, resolve_you
from .constants import (
    FALLBACK_REF,
    FUZZY_FLOOR,
    MAINLINE_CANDIDATES,
    SEED_CONF,
    SIBLING_MAX_EVIDENCE,
)
from .gates import (
    check_claim,
    check_not_asked,
    portability_problem,
    refuse_problems,
    repo_problem,
    report_evidence,
)
from .lint import warn_missing_about
from .model import (
    Answer,
    author_sig,
    band,
    confidence,
    local_today,
    mainline_ref,
    on_mainline,
    ref_state,
    render_header,
    repo_name,
)
from .rules import warn_missing_rules
from .scoring import build_scorer, normalize
from .store import Entry, add_cache_row, all_index, find_answer, find_entry

PORTABILITY = "hardcoded personal path"
REPO_PATH = "Repo: is a machine path"


def _as_list(v):
    """argparse `append` gives a list; a bare string is still accepted."""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


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
    chosen = [kind for kind, on in ((SHARED, args.shared), (LOCAL, args.local),
                                    (DEPUTY, getattr(args, "deputy", False))) if on]
    if not chosen and len(ledgers) == 1:
        return ledgers[0]
    if len(chosen) != 1:                   # none, or more than one
        sys.exit("say which ledger: --shared (the team can read it, forever), --local "
                 "(this machine only), or --deputy (your past decisions for the deputy). "
                 "Shared is append-only — ask the human before filing anything "
                 "machine-specific, path-specific or personal there.")
    # No fallback: a kind whose root is not open is refused, never filed elsewhere.
    return pick(ledgers, chosen[0], getattr(args, "context", None))


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
    a = find_answer(e, args.answer)
    kind = locate(args.ledgers, args.slug).kind
    if path_repo := repo_problem(args.repo, kind, args.force):
        refuse_problems(f"set-repo {e.slug} {a.aid}", [(REPO_PATH, path_repo)])
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
    a = find_answer(e, args.answer)
    if a.hash != before:
        sys.exit(f"BUG: writing Repo: changed the hash {before} → {a.hash}. Repo must stay "
                 f"out of the hash or every signature on this answer is voided.")
    yes, no, void = a.tally()
    print(f"{e.slug} {a.aid}  Repo: {note}   {yes}✓/{no}✗ intact, {void} voided "
          f"(unchanged), h={a.hash}")


def cmd_add_evidence(args, root):
    """Append a check to an existing answer. Voids no signature.

    Append only — it refuses a duplicate and never edits or removes a line; `lint`
    enforces the same against what is committed.
    """
    e = find_entry(root, args.slug)
    a = find_answer(e, args.answer)
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
    a = find_answer(e, args.answer)
    if a.hash != before:
        sys.exit(f"BUG: appending a check changed the hash {before} → {a.hash}. Evidence "
                 f"must stay out of the hash or every signature here is voided.")
    yes, no, void = a.tally()
    print(f"{e.slug} {a.aid}  checks {was} → {len(a.evidences)}   {yes}✓/{no}✗ intact, "
          f"{void} voided (unchanged), h={a.hash}")
    print("     standing signatures carry the depth they verified at; a new signature "
          "records the full set.")


def cmd_vote(args, root):
    """Add checks to a recorded answer whose claim matches on a similar question.

    The similar questions are the ones `resolve` scores above its floor. Prints
    `VOTED`/`UNCHANGED` for the answer it voted on. Otherwise prints one
    `SAME-QUESTION` line per entry that asks the same question, then `NO-VOTE`,
    and exits 1 so the caller can write a new entry.
    """
    claim_key, question_key = normalize(args.claim), normalize(args.question)
    entries = all_index(args.ledgers)
    score = build_scorer(set(question_key), entries)
    matched, same_question = None, []
    for c in entries:
        if score(c.tokens()) < FUZZY_FLOOR:
            continue
        lg_root = pick(args.ledgers, c.kind).root if c.kind else root
        e = find_entry(lg_root, c.slug, c.kind)
        if normalize(e.question) == question_key:
            same_question.append(e.slug)
        for a in e.answers:
            if matched is None and not a.asserted and normalize(a.claim) == claim_key:
                matched = (e, a, lg_root)
    if matched is None:
        for slug in same_question:
            print(f"SAME-QUESTION {slug}")
        print("NO-VOTE no similar question has an answer with this claim")
        return 1
    e, a, lg_root = matched
    evidence = [f"Evidence: {ev}" for ev in args.evidence]
    if all(ln in a.evidences for ln in evidence):
        print(f"UNCHANGED {e.slug} {a.aid}")
        return 0
    cmd_add_evidence(argparse.Namespace(**{**vars(args), "slug": e.slug, "answer": a.aid,
                                           "force": getattr(args, "force", False)}), lg_root)
    after = find_entry(lg_root, e.slug, e.kind)
    votes = len(next(x for x in after.answers if x.aid == a.aid).evidences)
    print(f"VOTED {e.slug} {a.aid} n={votes}")
    return 0


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
    if path_repo := repo_problem(getattr(args, "repo", None), lg.kind, args.force,
                                 local_option=True):
        problems.append((REPO_PATH, path_repo))
    refuse_problems(f"new {args.slug}", problems)
    report_evidence(args.evidence, root, lg.kind, getattr(args, "context", None))
    path.parent.mkdir(parents=True, exist_ok=True)
    a = Answer("a1", args.claim, SEED_CONF, str(local_today()), False, 0)
    a.because = f"Because: {args.because}"
    a.evidences = [f"Evidence: {ev}" for ev in _as_list(args.evidence)]
    context = getattr(args, "context", None)
    you = resolve_you(args.as_, context)
    a.repo, a.ref = _scope_lines(args)
    conf = confidence(0, 0)
    body = [f"# {args.slug}", f"Q: {args.q}"]
    if args.alt_terms:
        body.append(f"alt_terms: {args.alt_terms}")
    body += ["", render_header(a, conf, str(local_today())), a.because, *a.evidences]
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
    warn_missing_rules(root, lg.kind, getattr(args, "prog", None) or current_program("memory-ledger", "ledger"))


def show_siblings(e: Entry, prog: str | None = None) -> None:
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
        conf0 = 1.00 if a0.asserted else a0.counted_confidence()
        print(f"   {a0.aid} · conf {conf0:.2f} [{band(conf0)}] · {yes}✓/{no}✗, "
              f"{a0.independent()} independent")
        print(f"      {a0.claim}")
        for ev in a0.evidences[:SIBLING_MAX_EVIDENCE]:
            print(f"      {ev}")
        if len(a0.evidences) > SIBLING_MAX_EVIDENCE:
            print(f"      … {len(a0.evidences) - SIBLING_MAX_EVIDENCE} more check(s) — "
                  f"`{prog or current_program('memory-ledger', 'ledger')} show {e.slug}`")
    print("   → keep the checks you still agree with: --keep-evidence <aN>")
    print("   → the claim stays one falsifiable sentence; the disagreement goes in Because:")


def cmd_rival(args, root):
    you = resolve_you(args.as_, getattr(args, "context", None))
    e = find_entry(root, args.slug)
    show_siblings(e, getattr(args, "prog", None))
    kind = locate(args.ledgers, args.slug).kind
    problems = []
    if long_claim := check_claim(args.claim, args.force):
        problems.append(("claim too long", long_claim))
    if port := portability_problem(args.evidence, kind, args.force):
        problems.append((PORTABILITY, port))
    if path_repo := repo_problem(getattr(args, "repo", None), kind, args.force):
        problems.append((REPO_PATH, path_repo))
    refuse_problems(f"rival {e.slug}", problems)
    report_evidence(args.evidence, root, kind, getattr(args, "context", None))
    # max+1, never count+1. An answer id is immutable and gets referenced by
    # number from other answers, so a reused id makes one reference point at two
    # different bodies — and `_get_answer` returns the first match, so a `sign`
    # would land on whichever came first. Counting reuses an id after any gap.
    used = [int(x.aid[1:]) for x in e.answers if x.aid[1:].isdigit()]
    aid = f"a{max(used, default=0) + 1}"
    a = Answer(aid, args.claim, SEED_CONF, str(local_today()), False, 0)
    a.because = f"Because: {args.because}"
    # Checks carried over from an answer this one disagrees with, ahead of the
    # new one. A correction usually leaves most of the old ground standing, and
    # re-typing those lines by hand is how they drift into near-copies that hash
    # differently for no reason. Kept first, so the file reads as "what still
    # holds, then what overturns it"; order is part of the hash.
    inherited: list[str] = []
    for aid0 in _as_list(getattr(args, "keep_evidence", None)):
        for ev in find_answer(e, aid0).evidences:
            if ev not in inherited:
                inherited.append(ev)
    a.evidences = inherited + [f"Evidence: {ev}" for ev in _as_list(args.evidence)
                               if f"Evidence: {ev}" not in inherited]
    a.repo, a.ref = _scope_lines(args)
    conf = confidence(0, 0)
    e.lines += [render_header(a, conf, str(local_today())), a.because, *a.evidences]
    e.lines += [ln for ln in (a.repo, a.ref) if ln]
    e.lines += [author_sig(you, a.hash, len(a.evidences)), ""]
    e.write()
    print(f"added {aid} to {e.slug}  conf {conf:.2f} [{band(conf)}]  ✓ {you} (author)"
          f" — 0 independent yet   [{a.scope_label}]")


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
    a = find_answer(e, args.answer)
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
    if on_mainline(a.ref_value, to):
        sys.exit(f"{e.slug} {a.aid} is already scoped to {to}")
    for other in e.answers:
        if on_mainline(other.ref_value, to) and other.claim == a.claim:
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
    n = Answer(aid, a.claim, SEED_CONF, str(local_today()), False, 0)
    n.because = a.because
    n.evidences = list(a.evidences)
    # Promotion changes which ref the claim is about; it never moves the claim to
    # a different checkout, so `Repo:` carries across untouched.
    n.repo = a.repo
    n.ref = f"Ref: {to}"
    conf = confidence(0, 0)
    e.lines += [render_header(n, conf, str(local_today())), n.because, *n.evidences,
                *[ln for ln in (n.repo, n.ref) if ln], author_sig(you, n.hash, len(n.evidences)), ""]
    e.write()
    print(f"promoted {e.slug} {a.aid} ({a.ref_value}) → {aid} ({to})  "
          f"conf {conf:.2f} [{band(conf)}]  ✓ {you} (author)")
    print(f"{a.aid} is unchanged and keeps its {len(a.sigs)} signature(s) — they verified "
          f"it against {a.ref_value}, which is still true. {aid} starts unconfirmed: "
          f"nobody has yet run the check against {to}.")
