"""Write assertions and signatures without changing answer bodies."""

from __future__ import annotations

import sys

from .config import resolve_you
from .constants import (
    OUTPUT_PREFIX,
    OUTPUT_RE,
)
from .gates import (
    refuse_problems,
)
from .model import (
    asserted_line,
    band,
    git_user,
    is_confirmed_preference,
    local_today,
    render_header,
    sig_line,
    split_evidence,
)
from .store import find_answer, find_entry


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
    a = find_answer(e, args.answer)
    before = a.hash
    yes, no, _ = a.tally()
    counted = a.counted_confidence()

    if args.clear:
        if is_confirmed_preference(a):
            sys.exit("REFUSED use a confirmed Deputy replacement for an evidence-free assertion")
        if not a.asserted:
            sys.exit(f"{e.slug} {a.aid} is not asserted — nothing to clear")
        if a.asserted_line:
            e.lines.remove(a.asserted_line)
        a.asserted = False
        # header_idx is unmoved: the Asserted: line always sits below it.
        e.lines[a.header_idx] = render_header(a, counted, str(local_today()))
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
    e.lines[a.header_idx] = render_header(a, 1.00, str(local_today()))
    e.write()

    e = find_entry(root, args.slug)
    a = find_answer(e, args.answer)
    if a.hash != before:
        sys.exit(f"BUG: writing Asserted: changed the hash {before} → {a.hash}. It must stay "
                 f"out of the hash or every signature on this answer is voided.")
    print(f"{e.slug} {a.aid}  conf 1.00 [asserted] by {who}   {yes}✓/{no}✗ intact, "
          f"tally counts {counted:.2f}, h={a.hash}")
    print(f"     {line}")
    print("     the tally keeps running underneath; `assert --clear` hands the header back "
          "to it.")

def cmd_hash(args, root):
    a = find_answer(find_entry(root, args.slug), args.answer)
    if a.hash is None:
        sys.exit(f"{args.slug} {args.answer}: missing Because:/Evidence: — not verifiable")
    print(a.hash)

def cmd_sign(args, root):
    context = getattr(args, "context", None)
    you = resolve_you(args.as_, context)
    e = find_entry(root, args.slug)
    a = find_answer(e, args.answer)
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
    a = find_answer(e, args.answer)
    yes, no, _ = a.tally()
    conf = a.counted_confidence()
    # A pinned header is the human's; a vote joins the tally without rewriting it.
    # `checked` advances only on a new vote or a flipped one. `sign` never runs the
    # checks, so a correction that leaves the verdict alone must not be able to
    # present an old pass as freshly verified.
    if not a.asserted:
        moved = standing is None or standing["mark"] != mark
        e.lines[a.header_idx] = render_header(
            a, conf, str(local_today()) if moved else a.checked)
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
    a = find_answer(e, args.answer)
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
    a = find_answer(e, args.answer)
    yes, no, _ = a.tally()
    conf = a.counted_confidence()
    # A pinned header is the human's; a vote joins the tally without rewriting it.
    if not a.asserted:
        e.lines[a.header_idx] = render_header(a, conf, str(local_today()))
        e.write()
    print(f"{mark} {you} answers {target['who']}'s {target['mark']} → {e.slug} {a.aid}   "
          f"conf {conf:.2f}  [{band(conf)}]  ({yes}✓/{no}✗, {a.independent()} independent)")
    print(f"reply recorded under your signature — {target['who']}'s vote still stands, "
          f"as it must")
