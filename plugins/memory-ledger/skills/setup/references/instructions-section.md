# Instructions-file section

The facts a two-ledger setup adds, and nothing more:

- Reads span both ledgers; `--only shared|local` narrows.
- `new` needs `--shared` or `--local`, and there is no default.
- Shared history is append-only. Judge the entry and write it; ask only when you
  genuinely cannot place it — it reads general but leans on this machine, or it
  is about a person.
