# Instructions-file section

The facts the setup adds, and nothing more:

- Reads span every open ledger; `--only shared|local|deputy` narrows.
- `new` needs `--shared`, `--local` or `--deputy`, and there is no default.
- Shared history is append-only. Judge the entry and write it; ask only when you
  genuinely cannot place it — it reads general but leans on this machine, or it
  is about a person.
