# Mechanical writing checks

Run `check --kind procedure|description --files FILE...` for selected Markdown files.
Select `procedure` for instructions or `description` for descriptive text.
Use the host route in Host mechanics. Supply no task folder or checkpoint input.

Apply the respective sentence limits of 20 and 25 words.
Check prose paragraphs, list items and table cells. Join wrapped prose lines.
Exclude headings, fenced code and link destinations. Count link labels as visible prose.
Count each inline code span and each hyphenated group as one word.
Check parenthetical text separately. Count each parenthetical group as one word in the enclosing sentence.
Treat a colon before a vertical list as the end of that counted sentence.

Read each finding at its reported file and line. Review its word count, limit and text.
Read all file diagnostics. Correct unreadable inputs before relying on coverage.
Use exit 0 for `passed`, 1 for `needs-reading`, 2 for `refused` and 3 for `unavailable`.
Treat unreadable input as `unavailable`, even when the result retains text findings.
Use `--json` or `--prose` to select output. Without either flag, honor `BOOTGEAR_OUTPUT`.

Read the result's supported checks, counting policy and limitations.
Check meaning, vocabulary, grammar, structure and other ASD-STE100 counting rules through author reading.
Review each finding before changing the text. The command makes no text changes.
Keep this result separate from the author's declared checkpoint result.
