# Mechanical writing check

Run `check --kind procedure|description --files FILE...`. Omit task folder and checkpoint input.
Use 20 words per procedural sentence and 25 per descriptive sentence.

- Check paragraphs, list items, and table cells. Join wrapped prose.
- Exclude headings, fenced code, and link destinations. Count visible link labels.
- Count inline code spans and hyphenated groups as one word each.
- Check parentheses separately. Count each group as one word in its enclosing sentence.
- End a counted sentence at a colon before a vertical list.

Read findings at their reported lines. Check count, limit, and text. Correct unreadable files before relying on coverage.
Exit codes are `0 passed`, `1 needs-reading`, `2 refused`, and `3 unavailable`.
An unreadable file gives `unavailable` even with findings.
Use `--json` or `--prose`. Without either, honor `BOOTGEAR_OUTPUT`.

Read the limits in the result. Manually check meaning, vocabulary, grammar, structure, and other ASD-STE100 rules.
Review each finding before edits. The command changes no text and records no author result.
