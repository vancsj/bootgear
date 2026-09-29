"""Where the ledgers live, and which session is signing.

Two roots, not one: the difference between them is a git remote, and git history
is append-only, so a repo that has ever held a machine-local fact cannot later be
pushed to the team without publishing it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .constants import DEFAULT_LOCAL_ROOT, DEFAULT_SHARED_ROOT, KINDS, LOCAL, SHARED
from .context import InvocationContext, contextual_path
from .identity import resolve_identity


def config_candidates(context: InvocationContext | None = None) -> list[Path]:
    """Where the config may live, best match first.

    Ordered locality-then-name: a directory-local file beats a home one, and at
    each level the tool's own `.memory-ledger/` beats `.bootgear/`. `.bootgear/`
    is the wider framework this ledger ships inside, and it is read second
    precisely so the ledger keeps working for anyone who installed it on its own
    and never had that directory. Neither is required; with no config file at
    all the defaults apply.
    """
    base = context.cwd if context is not None else Path.cwd()
    return [base / ".memory-ledger/config.yaml",
            base / ".bootgear/config.yaml",
            Path.home() / ".memory-ledger/config.yaml",
            Path.home() / ".bootgear/config.yaml"]


def _parse_flat_yaml(text: str) -> dict:
    """One level of nesting, scalar values. Enough for the config file."""
    out: dict = {}
    parent = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indented = raw[0] in " \t"
        line = raw.strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip().strip("'\"")
        if indented and parent is not None:
            out.setdefault(parent, {})[key] = val
        elif val:
            out[key] = val
            parent = None
        else:
            parent = key
            out.setdefault(key, {})
    return out


def load_config(context: InvocationContext | None = None) -> dict:
    for candidate in config_candidates(context):
        if candidate.is_file():
            return _parse_flat_yaml(candidate.read_text(encoding="utf-8"))
    return {}


class Ledger:
    """One root, and whether what lives in it may leave this machine.

    Two ledgers rather than one folder convention inside a single repo, because
    the difference is a git remote and history is append-only. A repo that has
    ever held a machine-local fact cannot later be pushed to the team without
    publishing that fact — `git rm` does not unwrite history. Separate repos are
    the only split that survives the shared one gaining a remote.
    """

    __slots__ = ("kind", "root")

    def __init__(self, kind: str, root: Path):
        self.kind, self.root = kind, root

    @property
    def tag(self) -> str:
        return f"[{self.kind}]"

    def __repr__(self) -> str:
        return f"<Ledger {self.kind} {self.root}>"


def resolve_roots(shared_override: str | None = None,
                  local_override: str | None = None,
                  context: InvocationContext | None = None) -> dict[str, Path]:
    """Where each ledger lives. `memory.root` keeps naming the shared one.

    The existing key is not renamed: where `memory.root` or `$LEDGER_ROOT` is
    already set, it points at the team ledger, and silently re-pointing it at a
    local one would move writes to a repo that is never pushed — a failure with
    no symptom until the team notices nothing arrived.
    """
    cfg = load_config(context).get("memory") or {}
    shared = (shared_override or os.environ.get("LEDGER_ROOT")
              or cfg.get("root") or DEFAULT_SHARED_ROOT)
    local = (local_override or os.environ.get("LEDGER_LOCAL_ROOT")
             or cfg.get("local_root") or DEFAULT_LOCAL_ROOT)
    return {SHARED: contextual_path(shared, context), LOCAL: contextual_path(local, context)}


def open_ledgers(shared_override: str | None = None, local_override: str | None = None,
                 only: str | None = None,
                 context: InvocationContext | None = None) -> list[Ledger]:
    """The ledgers that exist on disk, shared first.

    A configured root that is not there is skipped rather than fatal, so a
    machine that has only ever had the shared ledger keeps working untouched and
    `setup` is what turns the second one on.
    """
    roots = resolve_roots(shared_override, local_override, context)
    if roots[SHARED] == roots[LOCAL]:
        sys.exit(f"shared and local ledger roots are the same path ({roots[SHARED]}) — "
                 f"they must be separate repos, or the shared one can never gain a remote "
                 f"without publishing local-only history. Run /memory-ledger:setup.")
    out = [Ledger(k, roots[k]) for k in KINDS
           if (only is None or k == only) and roots[k].is_dir()]
    if not out:
        want = ", ".join(f"{k}={roots[k]}" for k in KINDS if only is None or k == only)
        sys.exit(f"no ledger root found ({want}) — run /memory-ledger:setup")
    return out


def pick(ledgers: list[Ledger], kind: str,
         context: InvocationContext | None = None) -> Ledger:
    for lg in ledgers:
        if lg.kind == kind:
            return lg
    sys.exit(f"no {kind} ledger on disk ({resolve_roots(context=context)[kind]}) — run /memory-ledger:setup")


def locate(ledgers: list[Ledger], slug: str) -> Ledger:
    """Which ledger holds this slug. Ambiguity is an error, never a first-match.

    A slug present in both is a real defect — the same question settled twice,
    once where the team can see it and once where they cannot — and picking one
    silently means half the sessions sign a body the other half never read.
    """
    hits = [lg for lg in ledgers if (lg.root / slug).with_suffix(".md").is_file()]
    if len(hits) > 1:
        sys.exit(f"{slug} exists in {' and '.join(h.kind for h in hits)} — one question, one "
                 f"home. Delete the copy that does not belong, or give them distinct slugs.")
    if not hits:
        looked = ", ".join(str((lg.root / slug).with_suffix('.md')) for lg in ledgers)
        sys.exit(f"no entry at {looked}")
    return hits[0]


def resolve_you(explicit: str | None = None,
                context: InvocationContext | None = None) -> str:
    """A signature identifies the AI session that re-ran the evidence.

    Never the human: one person across many sessions would be one vote, which is
    the opposite of the consensus this ledger is built to accumulate.
    """
    return resolve_identity(context, explicit)
