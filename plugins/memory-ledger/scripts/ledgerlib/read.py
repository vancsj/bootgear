"""The commands that only read: resolve, show, list, resolve-roots."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from .config import KINDS, pick, resolve_roots
from .constants import FUZZY_FLOOR, RESOLVE_MAX_FOLDERS, RESOLVE_MAX_PER_FOLDER
from .gitops import _git
from .model import Answer, band, confidence, split_evidence
from .scoring import build_scorer, cut_candidates, mint_slug, normalize, query_coverage
from .store import Entry, all_entries, all_index, find_entry, tag_of


def age_days(checked: str | None) -> int | None:
    """Days since anything last happened to this answer, or None if undatable."""
    if not checked:
        return None
    try:
        return (date.today() - date.fromisoformat(checked)).days
    except ValueError:
        return None


def freshness(a: Answer, stale_after: int | None) -> str:
    """When this answer was last touched, both as a date and an age, flagged if
    past the staleness window.

    Both forms, not just one: the relative age is what a reader acts on ("is
    this worth re-running"), but a number of days keeps changing every time
    anyone runs `show` on the exact same content — an entry read today and
    again next month prints two different ages for a claim that has not
    changed at all. The absolute date is what actually happened and never
    rewrites itself.

    Staleness is reported, never used to hide a candidate. An entry withheld for
    being old is an entry a session cannot see it already has — so it writes the
    question again, and the ledger gains a duplicate whose only distinction is
    that it is younger. The reader decides; the resolver only tells them.
    """
    n = age_days(a.checked)
    if n is None:
        # An asserted header carries no date, and every caller already prints the
        # state label — repeating it here reads as two separate facts.
        return ""
    label = f" · checked {a.checked} ({n}d ago)"
    if stale_after is not None and n > stale_after:
        label += f"  ⚠ STALE (>{stale_after}d — re-run its Evidence line before using it)"
    return label


def render_answer_brief(a: Answer, width: int = 240,
                        stale_after: int | None = None) -> list[str]:
    """The lines a reader needs to decide sign-vs-rival, without a second call."""
    yes, no, _ = a.tally()
    counted = confidence(a.independent(), no)
    conf = 1.00 if a.asserted else counted
    state = "asserted" if a.asserted else band(conf)
    claim = a.claim if len(a.claim) <= width else a.claim[: width - 1] + "…"
    out = [(f"           {a.aid} · conf {conf:.2f} [{state}] · "
            f"{yes}✓/{no}✗, {a.independent()} independent{freshness(a, stale_after)}"
            # A pin suspends the header, never the evidence underneath.
            + (f"  (counted {counted:.2f})" if a.asserted else "")),
           f"              {claim}"]
    for ev in a.evidences:
        out.append(f"              {ev}")
    return out


def cmd_resolve(args, root):
    ledgers = args.ledgers
    query_tokens = normalize(args.text)
    query_set = set(query_tokens)
    print(f'RESOLVE  "{args.text}"')
    print(f"NORM     {' '.join(query_tokens)}")
    if len(ledgers) > 1:
        print(f"LEDGERS  {', '.join(f'{lg.kind}:{lg.root}' for lg in ledgers)}")

    entries = all_index(ledgers)
    if args.scope:
        scope = args.scope.strip("/")
        folders = sorted({str(Path(e.slug).parent) for e in entries})
        if scope not in folders:
            sys.exit(f"no such folder: {scope}\nfolders: {', '.join(folders)}")
        entries = [e for e in entries if str(Path(e.slug).parent) == scope]
        # Scoping is not a speed trick — scoring everything is already linear.
        # The point is that `df` recalibrates to the sub-corpus: a token common
        # enough to carry almost no weight across the whole ledger can still
        # separate entries inside one folder.
        print(f"SCOPE    {scope}/  ({len(entries)} entries; weights recomputed within it)")
    minted = mint_slug(args.text)

    for e in entries:
        if Path(e.slug).name == minted or e.slug == args.text.strip():
            # A cached row holds identity only, so the USE: redirect is read
            # from the entry file itself.
            redirect = e.redirect if isinstance(e, Entry) else \
                find_entry(pick(ledgers, e.kind).root if e.kind else root, e.slug).redirect
            target = redirect or e.slug
            print(f"EXACT    {target}{tag_of(e, ledgers)}"
                  + (f"  (USE-redirect from {e.slug})" if redirect else ""))
            print(f"next: {getattr(args, 'prog', 'ledger.py')} show {target}")
            return

    known, asked = query_coverage(query_set, entries)
    if asked and known < asked:
        unknown = sorted(t for t in query_set
                         if not any(t in e.tokens() for e in entries))
        print(f"UNKNOWN  {asked - known} of {asked} terms appear in no entry: "
              f"{' '.join(unknown)}")

    score = build_scorer(query_set, entries)
    scored = [(sc, e) for sc, e in ((score(e.tokens()), e) for e in entries)
              if sc >= FUZZY_FLOOR]
    if scored:
        ranked = cut_candidates(sorted(scored, key=lambda s: -s[0]))
        # Grouped by folder, but NOT filtered by folder. Routing to a single
        # folder first is unreliable when the target entry does not exist yet, and
        # a stage-1 miss is unrecoverable: the second stage searches a folder that
        # cannot hold the answer, finds nothing, and a duplicate gets minted —
        # the one failure this whole tool exists to prevent. Every entry is
        # still scored; the folders only decide how the list is laid out, which
        # is what keeps a flat top-5 from filling with noise as the ledger grows.
        # Keyed on (ledger, folder), never folder alone: the same folder path in
        # local and in shared are different homes, and collapsing them would hide
        # exactly the case a reader has to see — the same question filed on both
        # sides of the boundary.
        by_folder: dict[tuple, list] = {}
        for sc, e in ranked:
            by_folder.setdefault((e.kind, str(Path(e.slug).parent)), []).append((sc, e))
        order = sorted(by_folder, key=lambda f: -by_folder[f][0][0])
        for key in order[:RESOLVE_MAX_FOLDERS]:
            kind, f = key
            rows = by_folder[key]
            where = f"  [{kind}]" if kind and len(ledgers) > 1 else ""
            print(f"FOLDER   {f}/{where}   {len(rows)} candidate(s), best {rows[0][0]:.2f}")
            for sc, e in rows[:RESOLVE_MAX_PER_FOLDER]:
                hit = len(query_set & e.tokens())
                q = e.question if len(e.question) <= 92 else e.question[:91] + "…"
                print(f"   {sc:.2f} ({hit}/{asked})  {e.slug}{tag_of(e, ledgers)}")
                print(f"               Q: {q}")
            if len(rows) > RESOLVE_MAX_PER_FOLDER:
                print(f"   … {len(rows) - RESOLVE_MAX_PER_FOLDER} more in {f}/ "
                      f"— `ledger.py list --filter {f}`")
        if len(order) > RESOLVE_MAX_FOLDERS:
            rest = sum(len(by_folder[k]) for k in order[RESOLVE_MAX_FOLDERS:])
            print(f"         … {rest} weaker candidate(s) in "
                  f"{len(order) - RESOLVE_MAX_FOLDERS} more folder(s)")
        # The top candidate inline, so a session that only wants to know
        # whether the question is settled needs one call rather than four
        # (resolve, read the file, pick the answer, read its Evidence).
        _, top = ranked[0]
        print(f"         ── {top.slug}{tag_of(top, ledgers)} ──")
        top = find_entry(pick(ledgers, top.kind).root if top.kind else root, top.slug, top.kind)
        for a in top.answers:
            for line in render_answer_brief(a, stale_after=args.stale_after):
                print(line)
        print("         → same question? run that Evidence line, then sign or add a rival.")
        print("           Different question? mint below.")
    folders = sorted({d.name + "/" for lg in ledgers for d in lg.root.iterdir()
                      if d.is_dir() and not d.name.startswith(".")})
    # No GROUP line here: at resolve time the folder has not been chosen, so a
    # shared word is the only thing to group on and would propose folders named
    # after incidental words, sometimes ones that already exist. Folder shape is
    # a property of the whole tree, so `lint` reports it as REGROUP, once, where
    # the tree is visible.
    print(f"MINT     {minted}   (choose folder: {' '.join(folders) or 'none yet'})")
    if len(ledgers) > 1:
        print("         `new` needs --shared or --local. Ask before writing to shared: "
              "history is append-only, so a machine-local fact filed there cannot be "
              "unpublished later. Each ledger's rules: ledger.py rules.")


def cmd_show(args, root):
    """Read one entry.

    A slug arrives from a parent agent or a resolve; without a read verb a
    session either guesses a path or gives up, and the entry it was about to
    verify goes unsigned.
    """
    e = find_entry(root, args.slug)
    print(f"# {e.slug}")
    print(f"Q: {e.question}")
    if e.alt_terms:
        print(f"alt_terms: {', '.join(e.alt_terms)}")
    if e.redirect:
        print(f"USE: {e.redirect}")
    for a in e.answers:
        yes, no, void = a.tally()
        counted = confidence(a.independent(), no)
        conf = 1.00 if a.asserted else counted
        state = "asserted" if a.asserted else band(conf)
        print(f"\n## {a.aid} · conf {conf:.2f} [{state}] · {yes}✓/{no}✗"
              f", {a.independent()} independent"
              + (f", {void} voided by an edit" if void else "")
              + (f", tally counts {counted:.2f}" if a.asserted else "")
              + freshness(a, args.stale_after)
              + f"   [{a.scope_label}]")
        print(f"{a.claim}")
        for line in ([a.because] + a.evidences + [a.repo, a.ref, a.asserted_line]):
            if line:
                print(line)
        depth = len(a.evidences)
        for s in a.sigs:
            d = s.get("depth")
            shallow = (f"  [ran {d} of {depth} checks]"
                       if d is not None and d < depth else "")
            print(f"    {s['mark']} {s['who']} {s['date']}  h={s['hash']}"
                  + (f"  e={d}" if d is not None else "")
                  + ("  (author)" if s["author"] else "")
                  + shallow
                  + ("  [VOID — body changed since]" if s["hash"] != a.hash else ""))
            for ln in s.get("output", []):
                print(f"      > {ln}")
        if split_evidence(yes, no):
            print("    SPLIT — one body, both marks: the Evidence line depends on something "
                  "it does not name.")


def cmd_list(args, root):
    """Every answer, one line each, computed live.

    Deliberately not a file. A committed index is a second copy of the ledger
    that goes stale between the write and the lint, and the stale copy is the
    one someone reads.
    """
    ledgers = args.ledgers
    rows = 0
    heading = None
    for e in all_entries(ledgers):
        if Path(e.slug).name == "_about" and not args.all:
            continue
        if args.filter and args.filter not in e.slug and args.filter not in e.question.lower():
            continue
        top = (e.kind, e.slug.split("/")[0])
        if top != heading:
            heading = top
            label = f"{top[1]}" + (f"   [{e.kind}]" if e.kind and len(ledgers) > 1 else "")
            print(f"\n## {label}")
        for a in e.answers:
            _, no, _ = a.tally()
            counted = confidence(a.independent(), no)
            conf = 1.00 if a.asserted else counted
            state = "asserted" if a.asserted else band(conf)
            claim = a.claim if len(a.claim) <= 110 else a.claim[:109] + "…"
            print(f"  {conf:.2f} {state:<14} {e.slug} {a.aid} — {claim}"
                  + (f"   (counted {counted:.2f})" if a.asserted else ""))
            rows += 1
    counts = {lg.kind: sum(1 for e in all_entries([lg])
                           if Path(e.slug).name != "_about") for lg in ledgers}
    where = "  (" + ", ".join(f"{k}: {v} entries" for k, v in counts.items()) + ")" \
        if len(ledgers) > 1 else ""
    print(f"\n{rows} answer(s){where}")


def cmd_resolve_roots(args, root=None):
    """Where each ledger is and whether it is there yet — setup's read of the world.

    Deliberately outside `open_ledgers`, because setup runs before either root
    necessarily exists, and a command whose whole job is reporting a missing root
    cannot be one that exits on a missing root.
    """
    roots = resolve_roots(args.root, args.local_root, args.context)
    rows = []
    for kind in KINDS:
        pth = roots[kind]
        is_repo = (pth / ".git").exists()
        remote = ""
        if is_repo:
            remote = _git(pth, "remote", "get-url", "origin", check=False).stdout.strip()
        rows.append({"kind": kind, "path": str(pth), "exists": pth.is_dir(),
                     "git": is_repo, "remote": remote,
                     "entries": len([p for p in pth.rglob("*.md")
                                     if not p.name.endswith(".debate.md")]) if pth.is_dir() else 0})
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    for r in rows:
        state = ("missing" if not r["exists"] else
                 "not a git repo" if not r["git"] else
                 f"{r['entries']} entries, " + (f"remote {r['remote']}" if r['remote']
                                                else "no remote"))
        print(f"{r['kind']:<7} {r['path']:<40} {state}")
    return 0
