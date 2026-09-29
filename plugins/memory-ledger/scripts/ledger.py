#!/usr/bin/env python3
"""Command line for the memory-ledger skill.

The skill body is the constitution; `ledgerlib/` computes the parts that must
come out byte-identical for everyone — slug identity, signature hashes,
confidence — and this file is only the front door onto them.

    constants   the tunables, in one readable set
    config      where the two ledgers live, and which session is signing
    scoring     token identity and candidate ranking
    model       Answer, and the two computed values (h=, conf)
    store       entries on disk, and the identity cache
    gates       what `new` and `rival` refuse to write
    lint        drift, voided signatures, folder shape, cross-ledger collisions
    gitops      `save`: one commit per ledger
    read        resolve, show, list, resolve-roots
    write       new, rival, sign, refute, promote, assert
    selftest    pins the constants the skill body states in prose
    clikit      output mode, runnable refusals (shared byte-for-byte with engine)
"""
from __future__ import annotations

import argparse
import sys

from ledgerlib.audit import cmd_audit
from ledgerlib.clikit import Catalog, add_mode_flags, parser_class, run
from ledgerlib.config import locate, open_ledgers
from ledgerlib.context import InvocationContext
from ledgerlib.constants import (
    CLAIM_MAX_WORDS,
    DEFAULT_LOCAL_ROOT,
    DEFAULT_SHARED_ROOT,
    KINDS,
    SLUG_ADDRESSED,
)
from ledgerlib.doctor import cmd_doctor
from ledgerlib.gitops import cmd_save
from ledgerlib.lint import cmd_lint
from ledgerlib.read import cmd_list, cmd_resolve, cmd_resolve_roots, cmd_show
from ledgerlib.selftest import cmd_selftest
from ledgerlib.write import (
    cmd_add_evidence,
    cmd_assert,
    cmd_hash,
    cmd_new,
    cmd_promote,
    cmd_refute,
    cmd_rival,
    cmd_set_repo,
    cmd_sign,
)


# The argv after `ledger.py` that a refusal prints as the runnable shape of a
# command; a test parses every one with the real parser.
EXAMPLES = {
    "resolve": 'resolve "<question>"',
    "new": 'new <folder>/<slug> --q "<question>" --claim "<claim>" --because "<why>" '
           '--evidence "<check>" --local',
    "rival": 'rival <slug> --claim "<claim>" --because "<why>" --evidence "<check>"',
    "show": "show <slug>",
    "list": "list --filter <text>",
    "refute": 'refute <slug> a1 <signer-id> --output "<contradicting output>"',
    "hash": "hash <slug> a1",
    "sign": "sign <slug> a1",
    "lint": "lint",
    "promote": "promote <slug> a1 --to <ref>",
    "add-evidence": 'add-evidence <slug> a1 --evidence "<check>"',
    "assert": 'assert <slug> a1 --why "<ruling>"',
    "set-repo": "set-repo <slug> a1 <repo>",
    "save": "save",
    "resolve-roots": "resolve-roots",
    "audit": "audit",
    "doctor": "doctor --json",
    "selftest": "selftest",
}
FREQUENT = ("resolve", "show", "sign")
# resolve-roots, audit and doctor already own a `--json` that changes content or
# exit code, so it is never the mode flag; every command's prose is captured
# into `{"lines"}` in JSON mode.
CATALOG = Catalog(prog="ledger.py", examples=EXAMPLES, frequent=FREQUENT,
                  own_json=frozenset({"resolve-roots", "audit", "doctor"}),
                  capture=frozenset(EXAMPLES))
# Writes whose next step is committing them.
SAVE_NEXT = {"new", "rival", "sign", "refute", "promote", "add-evidence", "assert",
             "set-repo"}


def build_parser() -> argparse.ArgumentParser:
    p = parser_class(CATALOG)(prog="ledger.py", description=__doc__)
    p.add_argument("--root", metavar="PATH",
                   help=f"shared ledger root (default: memory.root / $LEDGER_ROOT / "
                        f"{DEFAULT_SHARED_ROOT})")
    p.add_argument("--local-root", dest="local_root", metavar="PATH",
                   help=f"local ledger root (default: memory.local_root / "
                        f"$LEDGER_LOCAL_ROOT / {DEFAULT_LOCAL_ROOT})")
    p.add_argument("--host", choices=("standalone", "claude", "codex", "gear"),
                   help="host adapter supplying context and signer identity")
    p.add_argument("--session-id", dest="session_id", metavar="ID",
                   help="exact host session identity used for signing")
    sub = p.add_subparsers(dest="cmd", required=True)

    def only_arg(p_):
        # Narrowing is opt-in and never the default. A read that silently covered
        # one ledger would let a session mint a question the other one already
        # answers, which is the single failure the resolver exists to prevent.
        p_.add_argument("--only", choices=KINDS, metavar="LEDGER",
                        help="restrict to one ledger (shared|local); both by default")

    r = sub.add_parser("resolve", help="claim text → existing entry or minted slug")
    r.add_argument("text")
    r.add_argument("--stale-after", dest="stale_after", type=int, metavar="DAYS",
                   help="flag answers not touched in this many days. Marks, never hides: "
                        "a candidate withheld for being old is one a session cannot see it "
                        "already has, so it writes the question again")
    r.add_argument("--in", dest="scope", metavar="FOLDER",
                   help="search only this folder, recomputing term weights within it. "
                        "Opt-in only: never infer the scope from the question — a wrong "
                        "guess searches a folder that cannot hold the answer, finds "
                        "nothing, and mints a duplicate")
    only_arg(r)

    def signer_arg(p_):
        p_.add_argument("--as", dest="as_", metavar="ID",
                        help="signer id (default: this session, from CLAUDE_CODE_SESSION_ID)")

    def authoring_args(p_):
        p_.add_argument("--ref", help="code ref this claim is about; omit for claims that are "
                                      "not code-scoped (business rules, policy)")
        p_.add_argument("--repo", help="checkout the Evidence lines run in; defaults to the "
                                       "current one when --ref is given, since a bare ref "
                                       "resolves in whatever repo the reader happens to be in")
        p_.add_argument("--force", action="store_true",
                        help=f"accept a claim longer than {CLAIM_MAX_WORDS} words, or a check "
                             f"that hardcodes a personal path")
        signer_arg(p_)

    n = sub.add_parser("new", help="seed an entry, carrying the author's own ✓")
    n.add_argument("slug")
    for flag in ("q", "claim", "because"):
        n.add_argument(f"--{flag}", required=True)
    n.add_argument("--evidence", required=True, action="append", metavar="CHECK",
                   help="a single check you can execute. Repeatable: give it once per "
                        "check rather than chaining with ; — a chain exits 0 on a partial "
                        "run, so a failure in the middle reads as success")
    n.add_argument("--alt-terms", dest="alt_terms")
    n.add_argument("--anyway", action="store_true",
                   help="seed despite a near-identical existing question (read it first)")
    n.add_argument("--shared", action="store_true",
                   help="file in the team ledger — the team can read it, and history is "
                        "append-only, so ask the human first")
    n.add_argument("--local", action="store_true",
                   help="file in the local ledger — this machine's paths, config and setup")
    authoring_args(n)

    v = sub.add_parser("rival", help="add a contradicting answer to an existing entry")
    v.add_argument("slug")
    for flag in ("claim", "because"):
        v.add_argument(f"--{flag}", required=True)
    v.add_argument("--evidence", required=True, action="append", metavar="CHECK",
                   help="a single check you can execute; repeatable")
    v.add_argument("--keep-evidence", dest="keep_evidence", action="append", metavar="aN",
                   help="carry over the checks from an existing answer you still agree "
                        "with; repeatable. They are kept ahead of your new ones")
    authoring_args(v)


    sh = sub.add_parser("show", help="print one entry: answers, conf, evidence, sigs, debate")
    sh.add_argument("slug")
    sh.add_argument("--stale-after", dest="stale_after", type=int, metavar="DAYS",
                    help="flag answers not touched in this many days")

    ls = sub.add_parser("list", help="every answer, one line each, computed live")
    ls.add_argument("--filter", help="only slugs/questions containing this text")
    ls.add_argument("--all", action="store_true", help="include _about entries")
    only_arg(ls)

    rf = sub.add_parser("refute", help="answer a standing signature with a contradicting run")
    rf.add_argument("slug")
    rf.add_argument("answer")
    rf.add_argument("sig", help="the signer id being answered")
    rf.add_argument("--output", required=True, help="the output that contradicts theirs")
    signer_arg(rf)

    h = sub.add_parser("hash", help="print h= for an answer")
    h.add_argument("slug")
    h.add_argument("answer")

    s = sub.add_parser("sign", help="record your ✓/✗, or correct the one you already cast")
    s.add_argument("slug")
    s.add_argument("answer")
    s.add_argument("--fail", action="store_true", help="record ✗ and open a debate file")
    s.add_argument("--output", help="the failing output to record in the debate file")
    s.add_argument("--as", dest="as_", metavar="ID",
                   help="signer id (default: this session, from CLAUDE_CODE_SESSION_ID)")

    li = sub.add_parser("lint", help="recompute conf, report drift/voids/orphans")
    li.add_argument("--fix", action="store_true")
    only_arg(li)

    pr = sub.add_parser("promote", help="re-scope a landed branch claim onto mainline")
    pr.add_argument("slug")
    pr.add_argument("answer")
    # No default here: resolving the mainline runs git, and doing that at parse
    # time would cost every subcommand a subprocess. `cmd_promote` asks the repo
    # it is standing in, and says so if the repo cannot answer.
    pr.add_argument("--to", metavar="REF",
                    help="ref to promote onto (default: this repo's mainline, from "
                         "origin/HEAD, or `ref:` in the config / $LEDGER_REF)")
    pr.add_argument("--force", action="store_true",
                    help="promote a ref ancestry says is unmerged, or a check that hardcodes "
                         "a personal path")
    # promote writes an answer now, so it signs one — same as new and rival.
    pr.add_argument("--as", dest="as_", help="signer id (default: this session)")

    ae = sub.add_parser("add-evidence",
                        help="append a check to an existing answer; voids no signature")
    ae.add_argument("slug")
    ae.add_argument("answer")
    ae.add_argument("--evidence", required=True, action="append", metavar="CHECK",
                    help="a check you can execute; repeatable. Append only — there is no "
                         "command that edits or removes one")
    ae.add_argument("--force", action="store_true",
                    help="append a check that hardcodes a personal path anyway")

    at = sub.add_parser("assert", help="pin an answer at 1.00 on a human's ruling, for a "
                                       "question no check can settle")
    at.add_argument("slug")
    at.add_argument("answer")
    at.add_argument("--why", help="what settles it — a decision, an intent, a system that no "
                                  "longer exists to be queried. Recorded in the entry")
    at.add_argument("--by", metavar="NAME",
                    help="who ruled (default: git config user.name). A human, never a "
                         "session: a signature says a check was re-run, an assertion says "
                         "a person decided")
    at.add_argument("--clear", action="store_true",
                    help="lift the assertion and hand the header back to the tally")

    sr = sub.add_parser("set-repo", help="name the checkout an existing answer's checks run in")
    sr.add_argument("slug")
    sr.add_argument("answer")
    sr.add_argument("repo")

    sv = sub.add_parser("save", help="lint --fix, stage every entry, commit, push — per ledger")
    sv.add_argument("-m", "--message", help="commit message (default: derived from what changed)")
    sv.add_argument("--no-push", action="store_true", help="commit only, even if a remote exists")
    sv.add_argument("--lint-detail", dest="lint_detail", action="store_true",
                    help="print every lint finding inline instead of the tally; "
                         "default is a one-line count by tag, `ledger.py lint` for the rest")
    only_arg(sv)

    rs = sub.add_parser("resolve-roots", help="print where each ledger is and whether it exists")
    rs.add_argument("--json", action="store_true", help="machine-readable, for setup")

    au = sub.add_parser("audit", help="Evidence lines that hardcode one person's home "
                                      "directory; --json dumps every answer for review")
    au.add_argument("--json", action="store_true",
                    help="dump every answer (question, claim, check) uncategorised, for a "
                         "reader to judge which ledger it belongs in")
    au.add_argument("--filter", help="only slugs/questions containing this text")
    only_arg(au)

    dr = sub.add_parser("doctor", help="check python, git, config and both roots")
    dr.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    sub.add_parser("selftest", help="verify the confidence and hash constants")
    add_mode_flags(p)
    return p


def _dispatch(args) -> int:
    args.prog = CATALOG.display_prog()
    args.context = InvocationContext.from_environment(
        host=args.host, session_id=args.session_id)
    # Both run before any root has to exist: selftest checks arithmetic, and
    # resolve-roots reports on roots that setup has not created yet.
    if args.cmd == "selftest":
        return cmd_selftest(args, None) or 0
    if args.cmd == "resolve-roots":
        return cmd_resolve_roots(args) or 0
    if args.cmd == "doctor":
        return cmd_doctor(args) or 0

    args.ledgers = open_ledgers(args.root, args.local_root,
                                only=getattr(args, "only", None), context=args.context)
    fn = {"resolve": cmd_resolve, "new": cmd_new, "rival": cmd_rival, "hash": cmd_hash,
          "show": cmd_show, "list": cmd_list,
          "sign": cmd_sign, "refute": cmd_refute, "promote": cmd_promote, "lint": cmd_lint,
          "save": cmd_save, "audit": cmd_audit, "set-repo": cmd_set_repo,
          "add-evidence": cmd_add_evidence, "assert": cmd_assert}[args.cmd]
    # A slug names exactly one entry, so the ledger that holds it is a lookup and
    # never a flag. Only `new` — where the entry does not exist yet — has to be
    # told, which is why that is the one command carrying --shared/--local.
    if args.cmd in SLUG_ADDRESSED:
        root = locate(args.ledgers, args.slug).root
    else:
        root = args.ledgers[0].root
    code = fn(args, root) or 0
    if code == 0 and args.cmd in SAVE_NEXT:
        print(f"next: {CATALOG.command('save')}")
    return code


def main():
    run(build_parser(), CATALOG, lambda a: a.cmd,
        dispatch=lambda a: sys.exit(_dispatch(a)))


if __name__ == "__main__":
    main()
