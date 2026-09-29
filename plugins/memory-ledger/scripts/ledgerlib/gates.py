"""What `new` and `rival` refuse to write, and why.

Every gate here exists because something could get into the ledger that should not
have: a claim too long to sign as a unit, an Evidence line naming a scratch file
that may not exist later, one whose regex silently matched nothing, and questions
already answered three folders away.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .audit import unportable_paths
from .clikit import refuse
from .config import Ledger
from .context import InvocationContext
from .constants import BROKEN_EVIDENCE, CLAIM_MAX_WORDS, DUPLICATE_GATE, FUZZY_FLOOR
from .scoring import build_scorer, cut_candidates, normalize
from .store import all_index, tag_of


def refuse_problems(what: str, problems: list[tuple[str, str]]) -> None:
    """Refuse once with every collected (kind, text) problem; no-op when empty.

    One refusal naming everything, rather than one per run: each gate a writer
    trips costs a full re-run, and on `new` that re-run repeats every Evidence
    line before reaching the next gate."""
    if problems:
        refuse(f"refusing {what}: {len(problems)} problem(s) — nothing written", problems)


def check_claim(claim: str, force: bool) -> str | None:
    """One falsifiable sentence, or the vote it earns cannot mean anything.

    Where the claim is a paragraph, a verifier who finds one half true and the
    other false has to write the verdict out as prose instead of signing it. A
    single ✓/✗ has no way to say "the first clause is wrong and the second
    holds", so a claim that cannot be wrong as a unit cannot be signed as a unit.
    """
    n = len(claim.split())
    if n > CLAIM_MAX_WORDS and not force:
        return (f"claim is {n} words (max {CLAIM_MAX_WORDS}) — a signature is one ✓/✗ for "
                f"the whole claim, so a claim with independently-checkable parts cannot be "
                f"signed honestly. Split it into separate answers or entries, or pass "
                f"--force if it really is one indivisible fact.")
    return None


SHELL_BUILTINS = {"cd", "for", "while", "if", "test", "[", "echo", "export", "set"}


def is_shell_shaped(cmd: str) -> bool:
    """Whether bash is the tool this check is written for.

    The contract is "a single check you can execute **with your tools**", and a
    session's tools are not just a shell: a connector query written as
    `<Tool>: <what to ask it>` is a single, executable check that bash can only
    ever fail to parse. Running everything through bash and
    refusing what does not survive would reject exactly the findings worth
    recording most — the ones that cost a connector round-trip to re-derive.
    """
    head = cmd.strip().split()
    if not head:
        return False
    first = head[0].split("=")[0]
    if first.endswith(":"):          # prose, not a command: "<Tool>:", "Note:"
        return False
    return first in SHELL_BUILTINS or shutil.which(first) is not None


def _unportable(evidences, kind: str | None) -> list[tuple[int, str, list[str]]]:
    if kind == "local":
        return []
    offending = [(i, ev, unportable_paths(ev)) for i, ev in enumerate(evidences, 1)]
    return [(i, ev, p) for i, ev, p in offending if p]


def portability_problem(evidences, kind: str | None = None,
                        force: bool = False) -> str | None:
    """The refusal for a hardcoded personal path into a shared write, or None.

    Pure — nothing runs — so a writer collects it alongside every other gate and
    refuses once, before `report_evidence` spends up to 180 s per check.

    `kind` gates it the same way `audit` does: a local ledger never leaves this
    machine, so a hardcoded home path there is not a defect. Unset (a caller
    that has no ledger kind handy) checks anyway — a refusal on a local write
    that did not need one costs one `--force`; staying quiet on a shared write
    that did costs a check nobody else can ever run, recorded as if it were
    fine. `--force` is the same escape hatch `check_claim` already uses for its
    own gate, so a session that means to file the personal path anyway has a
    single familiar flag to reach for, not a new exception per gate.
    """
    if isinstance(evidences, str):
        evidences = [evidences]
    offending = _unportable(evidences, kind)
    if not offending or force:
        return None
    paths = sorted({p for _, _, ps in offending for p in ps})
    lines = "\n".join(f"  [{i}] {ev}" for i, ev, _ in offending)
    return (f"hardcodes {', '.join(paths)}, which only this machine can run:\n{lines}\n"
            f"Use a repo-relative path, or --repo <name> to name the checkout instead "
            f"of embedding its location; write this to the local ledger instead; or "
            f"pass --force to file the personal path anyway.")


def report_evidence(evidences, root: Path, kind: str | None = None,
                    context: InvocationContext | None = None) -> None:
    """Run each check separately and report each; never refuses.

    Identical warning text collapses to one line naming every evidence index it
    applies to — a multi-line answer whose lines share one defect (the same
    unset scratch var, the same missing binary) would otherwise repeat the same
    paragraph once per line, which reads as more distinct problems than there
    actually are.

    A hardcoded personal path that reached here was filed with `--force`
    (`portability_problem` refused it otherwise), so it is reported as a WARN.
    """
    if isinstance(evidences, str):
        evidences = [evidences]
    reports: dict[str, list[int]] = {}
    order: list[str] = []
    for i, ev in enumerate(evidences, 1):
        label = f"EVIDENCE[{i}/{len(evidences)}]" if len(evidences) > 1 else "EVIDENCE"
        msg = _check_one(ev, root, label, context)
        if msg is None:
            continue
        if msg not in reports:
            reports[msg] = []
            order.append(msg)
        reports[msg].append(i)
    for msg in order:
        idxs = reports[msg]
        prefix = f"[{', '.join(str(i) for i in idxs)}] " if len(evidences) > 1 else ""
        print(f"{prefix}{msg}" if prefix else msg)

    offending = _unportable(evidences, kind)
    if offending:
        paths = sorted({p for _, _, ps in offending for p in ps})
        print(f"WARN     hardcodes {', '.join(paths)} — filed anyway with --force. Only this "
              f"machine can run this check.")


def _check_one(evidence: str, root: Path, label: str = "EVIDENCE",
               context: InvocationContext | None = None) -> str | None:
    """Run the Evidence line if it is a shell command, and report — never refuse.

    Returns the report text so identical reports across several evidence lines
    can be grouped by the caller instead of each printing on its own; returns
    None for the ordinary success case, which always prints immediately since
    its line count is specific to that one evidence line.

    Two defects it catches: an entry naming a `/tmp` scratch file that may no
    longer exist, and one passing `|` to `git grep`, whose default basic
    regex takes it literally — so it exits 1 with no output and reads to a later
    verifier as a refutation of the claim rather than a defect in the check.
    Both are invisible until something runs the line.

    It reports rather than blocks. Refusing to record a finding because its
    check looked wrong from here costs more than an imperfect check does: the
    finding is what is expensive to re-derive, and the author is reading this
    output anyway. Non-shell checks are left alone entirely — bash is not the
    arbiter of whether a connector query is a real check.

    Run from the author's cwd, not the ledger root. The ledger root was chosen as
    "a neutral cwd a verifier signs from", and that verifier does not exist:
    whoever asks this question next is a session working in the repo the question
    is about, which is where the author is standing right now. Run from the ledger
    root instead, perfectly good lines fail — `git grep … <mainline>` with no
    `-C` is the common shape, and any session in that repo runs it without trouble.
    A gate that cries wolf on good lines teaches authors to write through it.
    """
    cmd = evidence.strip()
    if not is_shell_shaped(cmd):
        return ("EVIDENCE not a shell command — not run. Whoever verifies this executes it "
                "with the tool it names; make sure that tool and its inputs are named in full.")
    try:
        p = subprocess.run(["bash", "-c", cmd],
                           capture_output=True, text=True, timeout=180,
                           cwd=context.cwd if context else None)
    except subprocess.TimeoutExpired:
        return ("WARN     Evidence line still running after 180s. A check nobody will wait for "
                "is a check nobody will re-run — consider narrowing it.")
    out = (p.stdout + p.stderr).strip()
    if p.returncode in (2, 126, 127) or BROKEN_EVIDENCE.search(out):
        return (f"WARN     Evidence line failed to run here (exit {p.returncode}):\n"
                f"           {out.splitlines()[0][:120] if out else '(no output)'}\n"
                f"         Check the quoting and the paths. It ran from your cwd, which is "
                f"where the next session asking this will be — so a failure here is a real one.")
    elif p.returncode != 0 and not out:
        return (f"WARN     Evidence exits {p.returncode} with no output. That is what a proven "
                f"absence looks like — and also what a broken pattern looks like. If it is "
                f"meant to match, check the regex: `git grep` is basic-regex, so `|`, `+` and "
                f"`?` need -E.")
    print(f"{label} ran, exit {p.returncode}, {len(out.splitlines())} line(s) of output")
    return None


def check_not_asked(question: str, slug: str, ledgers: list[Ledger],
                    anyway: bool) -> str | None:
    """Put the existing questions in front of the author, at the moment of writing.

    Asking authors to run `resolve` before `new` relies on memory: a slug gets
    typed from recall and the entry that already answers the question is never
    seen. Running the resolver here makes the comparison structural.

    It mostly prints rather than refuses, and that is a limit of the scoring, not
    timidity. Genuine duplicates are semantic — one entry's claim answers another's
    question while sharing almost no words — so they score no higher against each
    other than unrelated entries do. No threshold separates them, and a gate tuned
    to catch the real ones would refuse half the ledger. The gate above catches only
    a blatant restatement; the listing has to do the rest, because the reader is the
    only thing here that can tell two questions apart.

    Returns the restatement refusal text for the caller to collect; the listing
    is printed either way.
    """
    if Path(slug).name == "_about":
        return None                 # every _about asks the same question by design
    entries = all_index(ledgers)
    if not entries:
        return None
    q = set(normalize(question))
    score = build_scorer(q, entries)
    scored = [(sc, e) for sc, e in ((score(e.tokens()), e) for e in entries)
              if sc >= FUZZY_FLOOR and Path(e.slug).name != "_about"]
    if not scored:
        return None
    ranked = cut_candidates(sorted(scored, key=lambda s: -s[0]))
    print("EXISTING questions closest to yours — if one IS yours, stop and sign it "
          "or add a rival:")
    for sc, e in ranked:
        print(f"   {sc:.2f}  {e.slug}{tag_of(e, ledgers)}")
        print(f"         Q: {e.question}")
    top, top_e = ranked[0][0], ranked[0][1]
    if top >= DUPLICATE_GATE and not anyway:
        where = f" (in the {top_e.kind} ledger)" if top_e.kind and len(ledgers) > 1 else ""
        return (f"{top_e.slug} scores {top:.2f}{where} — that is a restatement, "
                f"not a new question. `sign` it, `rival` it, or pass --anyway if you have "
                f"read it and it genuinely asks something else.")
    return None
