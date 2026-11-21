"""Read and update the Engine session ledger."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from bootgear_cli import clikit
from bootgear_cli.clikit import current_program, refuse

from .session_decision_rules import _check_decisions_shape

PROG = current_program("engine", "task")
SECTIONS = ["settlement", "decisions", "todos", "pitches", "state"]
# Optional, after `## state` only: a column-0 `## machines` line inside an
# older ledger's settlement is settlement text, not this section.
MACHINES_SECTION = "machines"
DEFAULT_DIR = Path.home() / ".bootgear" / "session"
RUN_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def _command(rest: str) -> str:
    """A runnable `task` command line for a `next:` step."""
    return f"{PROG} {rest}"


def _effective_run_id(run_id: str | None) -> str:
    """Use an explicit run ID, else the session id from the host environment."""
    effective = clikit.session_id(run_id or None)
    if not effective:
        sys.exit(clikit.missing_session("<run-id>"))
    return effective


def _run_id_command(func):
    """Resolve the run identity before dispatching a session/state command."""
    def run(args):
        args.run_id = _effective_run_id(args.run_id)
        return func(args)
    run.__name__ = func.__name__
    return run


def _text_operand(args: argparse.Namespace) -> str:
    """The positional text or `--text`; refuse both or neither."""
    if args.text is not None and args.text_option is not None:
        sys.exit("text was given twice — use positional text or --text, not both")
    text = args.text if args.text is not None else args.text_option
    if text is None:
        sys.exit("missing text — pass --text <text>")
    return text


def _outcome_operand(args: argparse.Namespace) -> str:
    """The positional outcome or `--outcome`; refuse both or neither."""
    if args.outcome is not None and args.outcome_option is not None:
        sys.exit("outcome was given twice — use positional outcome or --outcome, not both")
    outcome = args.outcome if args.outcome is not None else args.outcome_option
    if outcome is None:
        sys.exit("missing outcome — pass --outcome succeeded|failed")
    return outcome


def _ledger_args(run_id: str, path: Path) -> str:
    """The run id when it differs from the session environment, and `--dir` off the default folder."""
    parts = [] if run_id == clikit.session_id() else [run_id]
    if path.parent.resolve() != DEFAULT_DIR.resolve():
        parts.append(f"--dir {shlex.quote(str(path.parent))}")
    return " ".join(parts)


def _ledger_command(verb: str, run_id: str, path: Path, rest: str = "") -> str:
    """A runnable `task <verb>` line for this ledger, its parts joined by single spaces."""
    return _command(" ".join(part for part in (verb, _ledger_args(run_id, path), rest) if part))


def _malformed(path: Path, problems: list[tuple[str, str]]) -> None:
    if problems:
        refuse(f"malformed ledger at {path}: {len(problems)} problem(s)", problems)


def _now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def _check_run_id(run_id: str, *, text_operand: bool = False) -> None:
    """Refuse an unsafe run id; with `text_operand`, a run id with whitespace names --text."""
    if not RUN_ID_RE.match(run_id) or ".." in run_id:
        hint = ("; pass text with --text <text>"
                if text_operand and any(char.isspace() for char in run_id) else "")
        sys.exit(f"invalid run-id '{run_id}' — letters, digits, '.', '_', '-' only, "
                 f"no path separators, no trailing newline{hint}")


def _ledger_path(run_id: str, base: Path | None = None, *, text_operand: bool = False) -> Path:
    _check_run_id(run_id, text_operand=text_operand)
    return (base or DEFAULT_DIR).resolve() / f"{run_id}.md"


def _read_text(path: Path) -> str:
    if not path.exists():
        sys.exit(f"no ledger at {path} — run `init` first")
    text = path.read_text()
    # Structure first: with a missing or duplicated heading the section
    # spans the other checks read are unreliable.
    _malformed(path, _check_structure(text))
    _malformed(path, _check_decisions_shape(_section_body(text, "decisions")) + _check_todos_shape(text))
    return text


def _read_text_ledger(path: Path, run_id: str) -> str:
    """`_read_text` for a text command; a missing run id beside the session's ledger names --text."""
    session = clikit.session_id()
    if not path.exists() and session and session != run_id and (path.parent / f"{session}.md").is_file():
        sys.exit(f"no ledger at {path} — run `init` first; pass text with --text <text>")
    return _read_text(path)


def _check_open(text: str, path: Path) -> None:
    # The heading's mere presence means closed, not just a non-empty body —
    # `close` always writes a body, so an empty `## closed` heading only
    # exists via hand-editing; treating it as still-open would let `close`
    # run again and append a second `## closed` heading, which
    # `_check_structure` then refuses to read at all, permanently.
    if _heading_re("closed").search(text) is not None:
        sys.exit(f"{path} is closed — no further writes accepted")


def _check_structure(text: str) -> list[tuple[str, str]]:
    """Every required section heading must appear exactly once, in the
    fixed order `init` writes them, before any command reads or writes the
    ledger. Presence alone isn't enough — a duplicated or reordered heading
    (e.g. hand-edited, or two '## todos') would let `_section_span` bind to
    the wrong occurrence and silently drop or misplace content on either
    side of it. Returns every (kind, item) problem found; none means sound."""
    problems: list[tuple[str, str]] = []
    positions = []
    for name in SECTIONS:
        matches = list(_heading_re(name).finditer(text))
        if not matches:
            problems.append(("missing section", f"'## {name}'"))
            continue
        if len(matches) > 1:
            problems.append(("duplicated section", f"'## {name}' ×{len(matches)}"))
        positions.append(matches[0].start())
    if positions != sorted(positions):
        problems.append(("sections out of order", f"expected {', '.join(SECTIONS)}"))
    closed = list(_heading_re("closed").finditer(text))
    if len(closed) > 1:
        problems.append(("bad closed heading", f"'## closed' ×{len(closed)}"))
    state = _heading_re(SECTIONS[-1]).search(text)
    if closed and state is not None and closed[0].start() < state.start():
        problems.append(("bad closed heading",
                         f"'## closed' must come after '## {SECTIONS[-1]}'"))
    if state is not None:
        machines = list(_heading_re(MACHINES_SECTION).finditer(text, state.end()))
        if len(machines) > 1:
            problems.append(("duplicated section",
                             f"'## {MACHINES_SECTION}' ×{len(machines)}"))
        if machines and closed and closed[0].start() < machines[0].start():
            problems.append(("bad closed heading",
                             f"'## closed' must come after '## {MACHINES_SECTION}'"))
    return problems


# A heading line is "## <name>" alone on its line, at column 0 — a section
# body line that merely starts with "## " (e.g. a markdown sub-heading inside
# a decision's own text) does not match, since it requires the exact known
# section name and a line boundary on both sides.
def _heading_re(name: str) -> re.Pattern:
    return re.compile(rf"(?m)^## {re.escape(name)}\s*$")


def _any_heading_re(extra: tuple[str, ...] = ()) -> re.Pattern:
    names = "|".join(re.escape(n) for n in SECTIONS + ["closed", *extra])
    return re.compile(rf"(?m)^## (?:{names})\s*$")


def _machines_heading(text: str) -> re.Match | None:
    """The `## machines` heading, searched only after `## state`."""
    state = _heading_re(SECTIONS[-1]).search(text)
    if state is None:
        return None
    return _heading_re(MACHINES_SECTION).search(text, state.end())


def _section_span(text: str, name: str) -> tuple[int, int]:
    """Start/end character offsets of a section's body (after its heading
    line). An absent `## closed` or `## machines` spans the empty end of the
    text."""
    if name == MACHINES_SECTION:
        match = _machines_heading(text)
    else:
        match = _heading_re(name).search(text)
    if match is None:
        if name in ("closed", MACHINES_SECTION):
            return len(text), len(text)
        sys.exit(f"malformed ledger: missing '## {name}' section")
    body_start = match.end() + 1
    rest = text[body_start:]
    after_state = name in (SECTIONS[-1], MACHINES_SECTION)
    next_heading = _any_heading_re((MACHINES_SECTION,) if after_state else ()).search(rest)
    body_end = body_start + (next_heading.start() if next_heading else len(rest))
    return body_start, body_end


def _section_body(text: str, name: str) -> str:
    start, end = _section_span(text, name)
    return text[start:end]


def _append_to_section(text: str, name: str, line: str) -> str:
    """Append a line to a section, normalizing to: one blank line after the
    heading (if any content follows it), entries with no blank lines between
    them, then exactly one blank line before the next heading.

    `text[:head_end]` always ends with the heading's own line plus exactly
    one blank line (that's how `init` writes every empty section, and how
    this function leaves it too) — so that blank line must not be
    re-added here, only the entries and the single blank line that follows
    them before whatever comes next."""
    head_end, end = _section_span(text, name)
    entries = [e for e in text[head_end:end].strip("\n").split("\n") if e.strip()]
    entries.append(line)
    body = "\n".join(entries) + "\n"
    if end < len(text):
        body += "\n"
    return text[:head_end] + body + text[end:]


def _write_atomic(path: Path, text: str) -> None:
    """Write via a fresh, unpredictable temp file in the same directory, then
    rename over the target. A fixed <name>.tmp path lets anything that can
    place a symlink there first redirect the write outside the ledger
    directory; mkstemp's random name and O_EXCL close that off."""
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                                     dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _check_no_embedded_heading(body: str, label: str) -> None:
    if _any_heading_re((MACHINES_SECTION,)).search(body):
        sys.exit(f"{label} contains a line that reads as a ledger section "
                  f"heading (e.g. '## todos' or '## closed') on its own —"
                  f" rename or rephrase that line so it isn't mistaken for "
                  f"real ledger structure")


def _single_line(value: str, label: str) -> str:
    if "\n" in value or "\r" in value:
        sys.exit(f"{label} cannot contain a line break — the ledger is one "
                  f"entry per line; split multi-point content across "
                  f"separate calls instead")
    value = value.strip()
    if not value:
        sys.exit(f"{label} cannot be blank")
    return value


def _check_todos_shape(text: str) -> list[tuple[str, str]]:
    """Re-check on every read that every todos-section entry has exactly the
    two checkbox states `update-todo` ever writes: `- [ ]` (open) or
    `- [x]` (done). Every
    todos entry is a checkbox — there's no freeform-note allowance in this
    section the way untagged legacy decisions entries get one in
    `_check_decisions_shape` — so a line that doesn't even start with `- [`
    is caught here too, not skipped as presumed-legitimate history; nothing
    ever legitimately writes one. A malformed checkbox (`- [y]`, `- []`,
    `- [xx]`, or no checkbox at all) is unusable either way — `read
    --open-only`'s filter only matches `- [ ]` exactly, so such an entry
    silently disappears from the open-todo view without being done either,
    and `update-todo`'s own `already_done` check only matches `- [x]`
    exactly, so it would treat the entry as open and rewrite its checkbox
    without ever surfacing that it was malformed to begin with. Checked
    against the whole line, not just its first 5 characters: `update-todo`
    always writes the checkbox, exactly one space, then the (non-empty,
    `_single_line`-checked) todo text — `- [ ]foo` (no space) and a bare
    `- [ ]`/`- [x]` (no text at all) are just as malformed as a wrong
    checkbox, and just as stuck: `update-todo` matches on `todo_text in e`
    to find a todo, so a bare checkbox with no text can never be matched by
    any `--done`/`--reopen` call, and `_single_line` refuses to record a
    blank text in the first place, leaving it permanently open. Returns
    one (kind, item) problem per malformed entry."""
    problems: list[tuple[str, str]] = []
    for entry in _section_body(text, "todos").split("\n"):
        stripped = entry.strip()
        if not stripped:
            continue
        if stripped[:6] not in ("- [ ] ", "- [x] ") or not stripped[6:].strip():
            problems.append(("bad todo checkbox", (
                f"{entry!r}: the checkbox isn't exactly '- [ ] ' or '- [x] ' "
                f"followed by non-empty text — not written by `update-todo`, or "
                f"hand-edited into a bad state")))
    return problems


RUN_ID_HELP = "the run id; the environment normally supplies it"
