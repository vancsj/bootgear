# Config file

```yaml
memory:
  root: <shared path>
  local_root: <local path>
```

Use the config path that `doctor` reports. The default is `~/.memory-ledger/config.yaml`.
A directory-local config wins over the home config. At each level, `.memory-ledger/` wins over `.bootgear/`.
Show only the `memory:` diff for an existing file. Preserve other keys.

Use `memory.deputy_root` for the deputy path. Its default is `~/.memory-ledger/deputy`.

| Root | Environment override | CLI override |
|---|---|---|
| Shared | `LEDGER_ROOT` | `--root` |
| Local | `LEDGER_LOCAL_ROOT` | `--local-root` |
| Deputy | `LEDGER_DEPUTY_ROOT` | `--deputy-root` |

CLI flags override environment values. Environment values override config.
