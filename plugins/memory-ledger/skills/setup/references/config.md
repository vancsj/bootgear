# Config file

```yaml
memory:
  root: <the shared ledger's path>
  local_root: <the local ledger's path>
```

Written to `~/.memory-ledger/config.yaml`. **`doctor` names the file it actually
read — write to that one**, not to a new file that will lose to it: a
directory-local `.memory-ledger/config.yaml` beats the home one, and `.bootgear/`
is read second at both levels. If the file exists, show a diff of the `memory:`
block rather than the whole file, and preserve everything else.
`$LEDGER_ROOT` / `$LEDGER_LOCAL_ROOT` override it; `--root` / `--local-root`
override those. The deputy root (`memory.deputy_root`, default
`~/.memory-ledger/deputy`) is set the same way with `$LEDGER_DEPUTY_ROOT` and
`--deputy-root`.
