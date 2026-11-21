"""Identify prose and code regions in Markdown standards."""

from __future__ import annotations

import re

# Group 1: the fence marker. Group 2: whatever follows it on the line — an
# opening fence may carry an info string there (e.g. ```text); a closing
# fence, per CommonMark, may not (only trailing whitespace is allowed). A
# backtick fence's info string additionally may not itself contain a
# backtick, per CommonMark — matched separately below so a line like
# "```bad`" is never treated as a valid fence opener at all (it isn't one),
# leaving whatever follows it in the document visible to the parser as
# ordinary text instead of being wrongly blanked as fence contents.
FENCE_RE = re.compile(r"^ {0,3}(```+(?!.*`)|~~~+)(.*)$", re.MULTILINE)


# Matches a complete HTML comment, however many lines it spans (DOTALL) —
# CommonMark's own comment syntax has no line restriction, unlike a fence's
# opening/closing markers. An unterminated "<!--" with no matching "-->"
# is left alone here rather than blanked to end-of-file the way an
# unclosed fence is: CommonMark itself treats stray "<!--" with no closer
# as literal text, not as an open block that swallows the rest of the
# document, so blanking to EOF here would blank real content CommonMark
# would still render.
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


# CommonMark HTML block type 1: a line starting (up to 3 leading spaces)
# with a case-insensitive `<pre`, `<script`, or `<style` tag, provided the
# next character is whitespace, `>`, or end of line (so `<pretend>` doesn't
# open one). Only these three tag names get the "runs verbatim until the
# matching closing tag, anywhere later on a line" treatment — the only
# other raw-HTML-block starts CommonMark defines (a handful of specific
# block-level tag names ending a paragraph, an XML declaration, a
# processing instruction, a CDATA section) are deliberately not handled
# here: unlike <pre>/<script>/<style>, several of those close on a blank
# line rather than a specific closing tag, which would need its own
# separate state-machine rule, and a rule-standard file mixing raw
# non-code HTML in with its rule text is not a pattern this validator
# otherwise needs to support. Handling just these three covers the concrete
# gap: a fake "## R### [sev]" heading pasted inside a <pre> block (e.g. showing forbidden syntax as an
# example) would otherwise validate as a real rule, and `</pre>` alone
# would count as that rule's "prose."
RAW_HTML_OPEN_RE = re.compile(
    r"^ {0,3}<(pre|script|style)(?=[ \t>]|$)", re.IGNORECASE | re.MULTILINE)


def _blank_span(text: str, start: int, end: int) -> str:
    return "".join("\n" if c == "\n" else " " for c in text[start:end])


def _blank_fences_and_comments(text: str) -> str:
    """Replace the contents of every fenced block (``` or ~~~, indented up
    to 3 spaces per CommonMark), every HTML comment, and every raw
    <pre>/<script>/<style> HTML block with blanks of the same shape, so a
    rule heading or top-level field written inside any of them is never
    parsed as real — while every other line/column keeps its original
    position for error reporting.

    All three are blanked in a single left-to-right scan, not independent
    passes, because any two of them can appear on the same line (or one
    inside another) and a naive pass order gets some direction wrong no
    matter which runs first:

    - Comments-then-fences would let a fence marker embedded inside a
      comment (e.g. a comment showing fence syntax) survive as a real
      fence-open marker, consuming real content past the comment's own
      close — the comment's blanking never gets a chance to protect it,
      since the fence pass runs on text that still has the marker intact.
    - Fences-then-comments would do the opposite: a real fence's closing
      marker line followed on the same line by comment-shaped text (e.g.
      "```<!-- not a closing fence -->") fails CommonMark's "closing fence
      must be bare" rule while the trailing text is still there, but a
      later comment-blanking pass turns that same trailing text to spaces
      first, making the line look bare — closing the fence early and
      exposing whatever comes after as real.
    - The same reasoning applies to a raw HTML block's own open tag: run a
      pass for it independently of comments/fences and a "<pre>" written
      inside a comment (or a fence) would wrongly be treated as a real
      block opener, consuming real content past that comment's/fence's own
      close.

    Scanning once, left to right, avoids all of this: while a construct is
    open (a fence or a raw HTML block — the two are mutually exclusive
    "open" states, and comments don't have one since they're always
    matched whole), only that construct's own closing rule is checked (its
    contents are verbatim — comment/fence/raw-HTML syntax inside it isn't
    recognized as such, per CommonMark, and closing-marker lines are
    judged against the real, unblanked trailing text so a same-line
    comment can never turn a non-bare fence closer into a bare one).
    While nothing is open, whichever of the next fence-open marker, the
    next comment start, or the next raw-HTML-block open tag comes first in
    the text is the one that actually opens — one fully containing another
    is blanked as a whole span before the other's scan ever reaches the
    marker inside it.

    A fence only closes on a matching character (``` never closes on ~~~
    or vice versa, per CommonMark), at least as many repeats of it, and no
    trailing info string (a closing fence must be bare — CommonMark permits
    only ordinary spaces/tabs trailing it, not any Unicode whitespace, so a
    bare .strip() would wrongly accept e.g. a trailing non-breaking space);
    an unclosed fence runs to the end of the file, so everything after it
    is blanked too. A raw HTML block closes at the first line containing
    its own tag name's closing form (`</pre>`, `</script>`, or `</style>`,
    case-insensitive) anywhere on the line — CommonMark does not require it
    to be bare the way a fence closer must be — and likewise runs to end of
    file if never closed. An unterminated comment ("<!--" with no matching
    "-->") is left alone rather than blanked to end-of-file the way an
    unclosed fence or raw HTML block is: CommonMark treats stray "<!--" as
    literal text, not an open block swallowing the rest of the document."""
    out = []
    pos = 0
    fence_iter = FENCE_RE.finditer(text)
    comment_iter = _HTML_COMMENT_RE.finditer(text)
    raw_html_iter = RAW_HTML_OPEN_RE.finditer(text)
    next_fence = next(fence_iter, None)
    next_comment = next(comment_iter, None)
    next_raw_html = next(raw_html_iter, None)
    open_marker: str | None = None  # fence marker text, when a fence is open
    open_raw_html_tag: str | None = None  # lowercased tag name, when a raw HTML block is open

    while True:
        while next_fence is not None and next_fence.start() < pos:
            next_fence = next(fence_iter, None)
        while next_comment is not None and next_comment.start() < pos:
            next_comment = next(comment_iter, None)
        while next_raw_html is not None and next_raw_html.start() < pos:
            next_raw_html = next(raw_html_iter, None)
        if (next_fence is None and next_comment is None and next_raw_html is None
                and open_raw_html_tag is None):
            break

        if open_raw_html_tag is not None:
            # `[ \t]*`, not `\s*` — the closing tag itself (`</pre>` etc.)
            # must be intact on one line, per CommonMark; `\s*` would also
            # match a newline between the tag name and `>` (e.g.
            # "</script\n>"), treating a close split across two lines as if
            # it were real, closing the block one line early and exposing
            # whatever comes after — up to and including a fake rule
            # heading — as validated real content instead of leaving it
            # blanked through to a genuine one-line close or EOF.
            close_re = re.compile(rf"</{open_raw_html_tag}[ \t]*>", re.IGNORECASE)
            close_m = close_re.search(text, pos)
            close_line_end = text.find("\n", close_m.end()) if close_m else -1
            block_end = close_line_end if close_line_end != -1 else len(text)
            inside = text[pos:block_end]
            out.append("\n" * inside.count("\n"))
            pos = block_end
            open_raw_html_tag = None
            continue

        if open_marker is not None:
            if next_fence is None:
                break
            m = next_fence
            char = open_marker[0]
            closes = (m.group(1)[0] == char and len(m.group(1)) >= len(open_marker)
                      and m.group(2).strip(" \t") == "")
            if closes:
                inside = text[pos:m.start()]
                out.append("\n" * inside.count("\n"))
                out.append(text[m.start():m.end()])
                pos = m.end()
                open_marker = None
            next_fence = next(fence_iter, None)
            continue

        candidates: list[re.Match[str]] = [
            c for c in (next_fence, next_comment, next_raw_html) if c is not None
        ]
        m = min(candidates, key=lambda candidate: candidate.start())
        if m is next_comment:
            out.append(text[pos:m.start()])
            out.append(_blank_span(text, m.start(), m.end()))
            pos = m.end()
            next_comment = next(comment_iter, None)
        elif m is next_raw_html:
            out.append(text[pos:m.end()])
            open_raw_html_tag = m.group(1).lower()
            pos = m.end()
            next_raw_html = next(raw_html_iter, None)
        else:
            out.append(text[pos:m.end()])
            open_marker = m.group(1)
            pos = m.end()
            next_fence = next(fence_iter, None)

    if open_raw_html_tag is not None:
        inside = text[pos:]
        out.append("\n" * inside.count("\n"))
        pos = len(text)
    if open_marker is not None:
        inside = text[pos:]
        out.append("\n" * inside.count("\n"))
        pos = len(text)
    out.append(text[pos:])
    return "".join(out)


# A line that carries no prose of its own: a genuine fence marker (its
# contents are already blanked by _blank_fences_and_comments by the time
# _split_rules runs, but the marker line itself, e.g. "```text", survives as
# literal text) or a complete one-line HTML comment. Used only to decide
# whether a rule's body has real prose — a body that is only fence markers
# and/or comments around blanked fence content is empty in substance even
# though `body.strip()` is non-empty, so checking `if not body` alone would
# wrongly accept it. Reuses FENCE_RE itself for the fence-marker half (not a
# second, looser backtick/tilde pattern) so a line FENCE_RE rejects as a
# fence at all — e.g. a backtick run whose info string itself contains a
# backtick, which CommonMark treats as ordinary text, not a fence opener —
# is never wrongly excluded from prose here either; the two checks must
# agree on what counts as a fence, or a line the fence logic already decided
# was real text could still be silently treated as a marker by this helper.
# The HTML-comment half is defensive, not load-bearing, when called from
# `validate()`: comments are already blanked by `_blank_fences_and_comments`
# in `validate()` itself before `_split_rules` ever runs, so a comment
# survives here only as content, but keeping the check makes `_has_prose`
# correct on its own if ever called without that preprocessing.
_NON_PROSE_LINE_RE = re.compile(r"^\s*<!--.*-->\s*$")


def _has_prose(body: str) -> bool:
    # RAW_HTML_OPEN_RE is checked too, the same reason FENCE_RE is: a raw
    # HTML block's opener survives _blank_fences_and_comments as literal
    # text (its own contents and closing tag are fully blanked), so a rule
    # whose body is only that opener — e.g. an empty "<script>...</script>"
    # pair with nothing between — has no real prose even though the
    # opener's own text makes `body.strip()` non-empty.
    return any(line.strip()
               and not _NON_PROSE_LINE_RE.match(line)
               and not FENCE_RE.match(line)
               and not RAW_HTML_OPEN_RE.match(line)
               for line in body.split("\n"))
