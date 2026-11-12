"""Fake host executables, their query log and the shared runtime link for the cli tests."""
from __future__ import annotations

from pathlib import Path

from bootgear_cli import runtime

HOSTS = ("claude", "codex")


def write_fake_host(directory: Path, host: str) -> Path:
    """A fake `host` that logs each call to $GEAR_TEST_QUERIES.

    It prints the file that $GEAR_TEST_<HOST>_LIST names. With $GEAR_TEST_HOST_FAIL set,
    it prints `host failed` to stderr and exits 1."""
    fake = directory / host
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import os\nimport sys\nfrom pathlib import Path\n"
        "with open(os.environ['GEAR_TEST_QUERIES'], 'a', encoding='utf-8') as log:\n"
        f"    log.write({host!r} + ' ' + ' '.join(sys.argv[1:]) + '\\n')\n"
        "if os.environ.get('GEAR_TEST_HOST_FAIL'):\n"
        "    print('host failed', file=sys.stderr)\n"
        "    raise SystemExit(1)\n"
        f"print(Path(os.environ['GEAR_TEST_{host.upper()}_LIST']).read_text(encoding='utf-8'), end='')\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


def query_count(queries: Path, host: str) -> int:
    """The number of `<host> plugin list --json` calls in the query log."""
    if not queries.is_file():
        return 0
    lines = queries.read_text(encoding="utf-8").splitlines()
    return sum(line == f"{host} plugin list --json" for line in lines)


def link_shared_runtime(data: Path) -> None:
    """Use the prepared runtime under the data root `data`; the store stays in `data`."""
    (data / "bootgear").mkdir(parents=True, exist_ok=True)
    (data / "bootgear" / "runtimes").symlink_to(runtime.environment_path().parent,
                                                target_is_directory=True)
