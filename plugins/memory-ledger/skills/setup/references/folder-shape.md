# Folder shape

`OVERSIZE` means a folder holds more direct entries than the cap and should be
split; the line names candidate sub-folders and marks the ones that already
exist, which are the cheapest splits because the destination and its `_about.md`
are already there. `REGROUP` is the softer version for folders under the cap.

Both are advisory and neither has a `--fix`. Offer to do a split; do not perform
one unasked. When you do move entries, fix the `# <slug>` header in each and
re-run `lint`.
