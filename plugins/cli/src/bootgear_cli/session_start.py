"""Accept SessionStart after the hook prepared session inventory."""

from bootgear_cli import clikit


def main() -> int:
    clikit.event_help("cli", "session-start", "stdin JSON from a native SessionStart hook.",
                      {"session_id": "example-session", "hook_event_name": "SessionStart"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
