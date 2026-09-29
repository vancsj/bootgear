"""Everything `lint` reports: drift, voided signatures, folder shape, collisions."""
from __future__ import annotations

import argparse
import re
import subprocess
from datetime import date
from pathlib import Path

from .config import Ledger
from .constants import (
    FOLDER_MAX_ENTRIES,
    GROUP_MIN_MEMBERS,
    REGROUP_MIN_FOLDER,
)
from .model import confidence, mainline_ref, ref_state, render_header, split_evidence
from .scoring import normalize
from .store import load_entries


def folder_members(entries) -> dict:
    """{folder: [entry, …]} for every folder that holds entries, at any depth.

    Keyed on the entry's actual parent, not on `slug.split("/")[0]`. Keying on how
    many parts a slug has only ever sees top-level folders, so a folder nested
    three deep can sit at any size while staying invisible to every grouping
    report for as long as it has existed. Depth is not what makes a folder too big.
    """
    from collections import defaultdict
    by_folder = defaultdict(list)
    for e in entries:
        if Path(e.slug).name == "_about":
            continue
        by_folder[str(Path(e.slug).parent)].append(e)
    return by_folder


def group_suggestions(entries, root: Path, min_members: int = GROUP_MIN_MEMBERS,
                      skip_existing: bool = True) -> dict:
    """Sub-folders the entries are already asking for: {folder: {token: [leaf, …]}}.

    A flat folder is the default nobody chooses — the resolver mints a leaf and
    offers top-level folders, so nesting only ever happens if something proposes
    it. This finds the shared token that several siblings already have in common
    and names it, so the grouping is a suggestion rather than an act of foresight.

    `skip_existing` drops tokens that already name a folder somewhere in the
    ledger, which is right for a REGROUP proposal: a standing report proposing a
    folder that already exists elsewhere in the tree is asking for a second home
    for one word, when the answer was to move the three entries into the home
    already there. Repeating it every lint run teaches the reader to skip the
    whole category.
    An OVERSIZE report wants the opposite, because "these eight belong in the
    folder you already have" is the most actionable split there is; it passes
    False and labels those tokens instead of hiding them.
    """
    from collections import defaultdict
    existing = {d.name for d in root.rglob("*") if d.is_dir()}
    out = {}
    for folder, members in folder_members(entries).items():
        counts = defaultdict(list)
        for e in members:
            for t in set(normalize(Path(e.slug).name.replace("-", " "))):
                if skip_existing and t in existing:
                    continue
                counts[t].append(Path(e.slug).name)
        best = {t: slugs for t, slugs in counts.items() if len(slugs) >= min_members}
        if best:
            out[folder] = best
    return out


def report_folder_shape(root: Path) -> int:
    """OVERSIZE for folders past the cap, REGROUP for clusters below it.

    One report per folder, never both. A folder over the cap has to be split, so
    a second line proposing a smaller regrouping of the same entries is noise on
    top of the instruction that already covers it.

    OVERSIZE names candidate sub-folders rather than just the count, because the
    count is a fact the reader can already see and does not tell them what to do
    about it. Tokens that already name a folder elsewhere
    are shown and labelled `→ existing`: those are the cheapest splits available,
    since the destination is already there and its `_about.md` is already written.
    """
    entries = load_entries(root)
    sizes = {f: len(m) for f, m in folder_members(entries).items()}
    tight = group_suggestions(entries, root)
    wide = group_suggestions(entries, root, skip_existing=False)
    # name → where that folder actually is, so a candidate whose home already
    # exists can name the real destination. `tech/parsing/lexer/ (38 → existing)`
    # reads as "make a new folder"; `tech/lexer/ (38, already exists)` reads as
    # "move them there", which is the action.
    existing: dict[str, str] = {}
    for d in sorted(root.rglob("*")):
        if d.is_dir() and not any(s.startswith(".") for s in d.parts):
            existing.setdefault(d.name, str(d.relative_to(root)))
    problems = 0

    for folder in sorted(sizes):
        n = sizes[folder]
        if n > FOLDER_MAX_ENTRIES:
            # A token that repeats a component of the folder's own path proposes
            # `tech/parsing/parsing/`, the folder saying its own name back.
            own = set(Path(folder).parts)
            cands = [(t, s) for t, s in
                     sorted(wide.get(folder, {}).items(), key=lambda kv: (-len(kv[1]), kv[0]))
                     if t not in own]
            shown = ", ".join(
                f"{existing[t]}/ ({len(s)}, already exists)" if t in existing
                else f"{folder}/{t}/ ({len(s)})"
                for t, s in cands[:4])
            print(f"OVERSIZE   {folder}/ holds {n} entries, cap is {FOLDER_MAX_ENTRIES} — split it. "
                  + (f"Candidates: {shown}" if shown else
                     "No token is shared by 3+ entries; split by meaning, not by name."))
            problems += 1
            continue
        if n < REGROUP_MIN_FOLDER:
            continue
        # A token that is a stem of the folder's own path is the folder saying its
        # own name back — a `tech/parsing/` folder reporting that its entries all
        # share "pars".
        # OVERSIZE already filters these; REGROUP did not, so grouping a folder
        # into existence immediately made it propose splitting itself.
        own = set()
        for part in Path(folder).parts:
            own |= set(normalize(part.replace("-", " ")))
        for tok, slugs in sorted(tight.get(folder, {}).items(), key=lambda kv: (-len(kv[1]), kv[0])):
            if tok in own:
                continue
            print(f"REGROUP    {folder}/ holds {len(slugs)} entries sharing \"{tok}\" — "
                  f"consider {folder}/{tok}/: {', '.join(sorted(slugs))}")
            problems += 1
            break
    return problems


def warn_missing_about(root: Path, path: Path):
    for d in path.parents:
        if d == root:
            break
        if not (d / "_about.md").is_file():
            print(f"WARN     {d.relative_to(root)}/ has no _about.md — orphan dir")


def lint_one(fix: bool, lg: Ledger, context=None) -> int:
    args = argparse.Namespace(fix=fix, context=context)
    root = lg.root
    problems = 0
    seen: dict[str, str] = {}
    for e in load_entries(root, lg.kind):
        leaf = Path(e.slug).name
        if leaf != "_about" and leaf in seen:
            print(f"DUPLICATE  {e.slug} collides with {seen[leaf]}")
            problems += 1
        seen.setdefault(leaf, e.slug)
        if not e.question and not e.redirect:
            print(f"NO-Q       {e.slug}")
            problems += 1
        # The `# <slug>` header is the only thing inside the file that says where
        # it lives, so a move that leaves it behind makes the entry claim a path
        # it is not at — and every reader who trusts the header looks in the
        # wrong place. A typical case is an entry moved into a new
        # sub-folder that keeps its old, truncated slug.
        want_header = f"# {e.slug}"
        if e.lines and e.lines[0].strip() != want_header:
            print(f"HEADER     {e.slug} — first line is {e.lines[0].strip()!r}, expected "
                  f"{want_header!r}" + ("  [fixed]" if args.fix else ""))
            problems += 1
            if args.fix:
                e.lines[0] = want_header
        ids = [a.aid for a in e.answers]
        for dup in sorted({i for i in ids if ids.count(i) > 1}):
            # Two answers sharing an id: every reference to it is ambiguous, and
            # `sign` silently addresses the first one.
            # Almost always a merge: two clones each allocated max+1 offline.
            # Renumbering is safe and costs nothing — the id is not part of the
            # hash, so every signature survives the change. What it can break is
            # a citation, so renumber the one nothing else names.
            print(f"DUP-ANSWER {e.slug} has {ids.count(dup)} answers called {dup} — every "
                  f"reference to {dup} is ambiguous and `sign` silently takes the first. "
                  f"Renumber the one no other answer cites; ids are not hashed, so no "
                  f"signature is voided by it")
            problems += 1
        for a in e.answers:
            if a.hash is None:
                print(f"NO-EVIDENCE {e.slug} {a.aid} — unverifiable, cannot be signed")
                problems += 1
                continue
            yes, no, void = a.tally()
            if void and not (yes or no):
                print(f"VOIDED     {e.slug} {a.aid} — {void} sig(s) predate an edit and "
                      f"nothing has verified the current body")
                problems += 1
            if a.asserted:
                # A pin suspends the header and nothing else; everything below
                # still runs.
                if not a.asserted_line:
                    print(f"ASSERT-UNRECORDED {e.slug} {a.aid} — pinned at 1.00 with no "
                          f"`Asserted:` line saying who ruled and what settles it. Run "
                          f"`ledger.py assert {e.slug} {a.aid} --why \"…\"`, or `--clear` "
                          f"to hand it back to the tally")
                    problems += 1
                if no:
                    print(f"ASSERTED-CONTESTED {e.slug} {a.aid} — pinned at 1.00 with {no}✗ "
                          f"standing; the tally counts {confidence(a.independent(), no):.2f}. "
                          f"A pin is not a veto: answer the ✗ with `refute`, or `assert "
                          f"--clear`")
                    problems += 1
            else:
                conf = confidence(a.independent(), no)
                if abs(conf - a.conf) >= 0.005:
                    print(f"DRIFT      {e.slug} {a.aid}  header {a.conf:.2f} → computed "
                          f"{conf:.2f}" + ("  [fixed]" if args.fix else ""))
                    problems += 1
                    if args.fix:
                        e.lines[a.header_idx] = render_header(a, conf, str(date.today()))
            rv = a.ref_value
            # The mainline is whatever THIS repo calls it, discovered per repo.
            # Comparing against a hardcoded name meant an answer correctly scoped
            # to a `main` repo's mainline was never recognised as the mainline
            # answer, so it was ref-checked on every run and never suppressed the
            # REF-LANDED line below.
            context = getattr(args, "context", None)
            mainline = mainline_ref(context=context)
            if rv and rv != mainline:
                state = ref_state(rv, a.repo_value, context)
                # A landed branch is only unfinished business while nothing in
                # the entry speaks for mainline yet. Once a sibling answer is
                # scoped to the mainline the question has been re-asked and
                # re-answered there, and repeating the line every run would ask
                # for a promotion that `promote` itself refuses — these checks
                # name their branch outright, so a copied one would read the
                # branch while claiming mainline.
                answered = any(o is not a and o.ref_value == mainline
                               and o.repo_value == a.repo_value for o in e.answers)
                if state == "merged" and not answered:
                    print(f"REF-LANDED {e.slug} {a.aid}  {rv} is now in {mainline} — "
                          f"add an answer scoped to mainline (`promote` if its checks do not "
                          f"name the branch, otherwise `rival` with a mainline check)")
                    problems += 1
                elif state == "missing" and a.repo_value:
                    print(f"REF-GONE   {e.slug} {a.aid}  {rv} resolves nowhere in "
                          f"{a.repo_value} — promote it if it landed, drop the entry if the "
                          f"branch was abandoned")
                    problems += 1
                elif state == "missing":
                    # Without a `Repo:` the ref was resolved against whatever
                    # checkout the caller stands in, so `missing` may mean only
                    # "wrong directory". REF-GONE tells the reader to delete a
                    # verified entry, and that must never rest on a guess.
                    print(f"REF-UNSCOPED {e.slug} {a.aid}  {rv} resolves nowhere here, but the "
                          f"answer names no repo — run `set-repo` to say which checkout it "
                          f"means before trusting that")
                    problems += 1
                # `unknown` (not in a repo) is deliberately silent. It is not
                # a problem with the ledger, and REF-GONE must never fire for it
                # — that line tells the reader to delete a verified entry.
            if split_evidence(yes, no):
                # Not "rewrite the Evidence line": an answer body is immutable, so
                # the disagreement is settled by an answer whose check names the
                # thing the split turned on, not by editing the one that did not.
                print(f"SPLIT      {e.slug} {a.aid}  {yes}✓/{no}✗ on one body — the check turns "
                      f"on something it does not name; add a rival whose check names it")
                problems += 1
        if args.fix:
            e.write()

    # A `.debate.md` here is a legacy sidecar: recorded output lives under the
    # signature that produced it, in the entry itself. Reported rather than
    # read, because nothing looks at these.
    for d in sorted(root.rglob("*.debate.md")):
        print(f"STRAY-DEBATE {d.relative_to(root)} — recorded output belongs under its "
              f"signature in the entry; nothing reads this file")
        problems += 1

    problems += report_folder_shape(root)

    for d in sorted(p for p in root.rglob("*")
                    if p.is_dir() and not any(s.startswith(".") for s in p.parts)):
        if not (d / "_about.md").is_file():
            print(f"NO-ABOUT   {d.relative_to(root)}/")
            problems += 1

    return problems


def evidence_rewrites(root: Path) -> int:
    """A removed or edited `Evidence:` line in the working tree.

    Evidence is outside the answer hash, so without this a hard check could be
    swapped for an easy one and the standing votes would ride along. Diffed
    against HEAD in one call, before `save` commits.

    A whole-file delete is not a rewrite — the entry it belonged to is gone, not
    a check quietly swapped out from under a standing signature — so its
    `+++ /dev/null` hunk is skipped rather than blamed on whichever path the
    diff last named.
    """
    p = subprocess.run(["git", "-C", str(root), "diff", "HEAD", "--unified=0", "--", "."],
                       capture_output=True, text=True)
    if p.returncode:
        return 0                      # not a repo, or nothing committed yet
    problems, current, deleted = 0, None, False
    for line in p.stdout.splitlines():
        if line.startswith("+++ "):
            deleted = line == "+++ /dev/null"
            current = None if deleted else line[6:]
        elif line.startswith("-Evidence:") and not deleted:
            print(f"EVIDENCE-REWRITTEN {current} — a check was removed or edited; "
                  f"checks are append-only, and signatures stand on the ones already there. "
                  f"Restore it and add a new one with `add-evidence`")
            problems += 1
    return problems


def cross_ledger_collisions(ledgers: list[Ledger]) -> int:
    """The same slug, or the same leaf, on both sides of the boundary.

    This is the failure two ledgers introduce and one ledger cannot have. A slug
    in both is one question with two sets of signatures, so neither tally is the
    real one. A shared *leaf* under different folders is softer — it may be two
    genuinely different questions — so it is reported and not treated as
    identical, the same way `DUPLICATE` reads within a single root.
    """
    if len(ledgers) < 2:
        return 0
    problems = 0
    homes: dict[str, list[str]] = {}
    leaves: dict[str, list[str]] = {}
    for lg in ledgers:
        for e in load_entries(lg.root, lg.kind):
            if Path(e.slug).name == "_about":
                continue
            homes.setdefault(e.slug, []).append(lg.kind)
            leaves.setdefault(Path(e.slug).name, []).append(f"{lg.kind}:{e.slug}")
    for slug, kinds in sorted(homes.items()):
        if len(kinds) > 1:
            print(f"TWO-HOMES  {slug} exists in {' and '.join(kinds)} — one question, one home. "
                  f"Neither tally is the real one until you delete the copy that does not belong.")
            problems += 1
    for leaf, where in sorted(leaves.items()):
        if len(where) > 1 and len({w.split(':')[0] for w in where}) > 1 \
                and leaf not in {Path(s).name for s in homes if len(homes[s]) > 1}:
            print(f"CROSS-LEAF {leaf} appears as {', '.join(where)} — check they are not the "
                  f"same question filed on both sides")
            problems += 1
    return problems


WIKILINK = re.compile(r"\[\[([a-z0-9][a-z0-9_-]*(?:/[a-z0-9][a-z0-9_-]*)*)\]\]")


def dangling_links(ledgers: list[Ledger]) -> int:
    """`[[slug]]` pointers that resolve to no entry in any ledger.

    Nothing else catches these. A link lives inside a claim or a `Because:` line,
    so it is part of the answer hash — which means the only sanctioned way to fix
    one is a new answer carrying the corrected text. That cost is exactly
    why the breakage has to be reported rather than discovered: a `git mv` during
    a folder split silently turns every inbound link into a pointer at nothing,
    and a reader following it finds no entry and cannot tell whether the claim
    was withdrawn or merely moved.

    The pattern requires slug shape (lowercase word segments joined by `/`) so
    it never matches a regex character class or a literal array sitting inside
    an `Evidence:` shell one-liner or a query-result note — `[[:space:]]` and
    `[[199,193,6]]` are not links, and reporting them as dead ones is a false
    positive, not a broken reference.

    Resolved across every ledger, not per-root, because a shared entry may
    legitimately reference something the local ledger settled.
    """
    known = {e.slug for lg in ledgers for e in load_entries(lg.root, lg.kind)}
    problems = 0
    for lg in ledgers:
        for e in load_entries(lg.root, lg.kind):
            for idx, line in enumerate(e.lines):
                for target in WIKILINK.findall(line):
                    if target in known:
                        continue
                    hashed = line.startswith(("## ", "Because:", "Evidence:", "Ref:"))
                    print(f"DEAD-LINK  {e.slug} → [[{target}]] resolves to no entry"
                          + ("  (in a hashed line — fixing it voids this answer's "
                             "signatures)" if hashed else ""))
                    problems += 1
    return problems


def cmd_lint(args, root):
    ledgers = args.ledgers
    problems = 0
    for lg in ledgers:
        if len(ledgers) > 1:
            print(f"── {lg.kind}: {lg.root} ──")
        n = lint_one(args.fix, lg, getattr(args, "context", None)) + evidence_rewrites(lg.root)
        problems += n
        if len(ledgers) > 1:
            print(f"   {n} problem(s) in {lg.kind}\n")
    problems += cross_ledger_collisions(ledgers)
    problems += dangling_links(ledgers)
    print(f"\n{problems} problem(s)" + ("" if args.fix else "  — rerun with --fix to rewrite conf"))
    return 1 if problems and not args.fix else 0
