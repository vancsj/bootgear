"""Fake host executables, their query log and the shared runtime link for the cli tests."""
from __future__ import annotations

import sys
from pathlib import Path

from bootgear_cli import runtime

HOSTS = ("claude", "codex")


def write_fake_host(directory: Path, host: str) -> Path:
    """A fake `host` that logs each call to $GEAR_TEST_QUERIES.

    It reads $GEAR_TEST_<HOST>_LIST and filters Codex scoped queries by marketplace.
    $GEAR_TEST_CODEX_MARKETPLACES supplies marketplace discovery when set.
    $GEAR_TEST_HOST_FAIL makes every call fail."""
    fake = directory / host
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json\nimport os\nimport sys\nfrom pathlib import Path\n"
        "with open(os.environ['GEAR_TEST_QUERIES'], 'a', encoding='utf-8') as log:\n"
        f"    log.write({host!r} + ' ' + ' '.join(sys.argv[1:]) + '\\n')\n"
        "if os.environ.get('GEAR_TEST_HOST_FAIL'):\n"
        "    print('host failed', file=sys.stderr)\n"
        "    raise SystemExit(1)\n"
        f"document = json.loads(Path(os.environ['GEAR_TEST_{host.upper()}_LIST']).read_text(encoding='utf-8'))\n"
        "args = sys.argv[1:]\n"
        f"if {host!r} == 'codex':\n"
        "    if args == ['plugin', 'marketplace', 'list', '--json']:\n"
        "        source = os.environ.get('GEAR_TEST_CODEX_MARKETPLACES')\n"
        "        document = (json.loads(Path(source).read_text()) if source else\n"
        "                    {'marketplaces': [{'name': 'fixture-marketplace', 'root': '/fixture'}]})\n"
        "    elif args == ['plugin', 'list', '--json']:\n"
        "        if os.environ.get('GEAR_TEST_CODEX_UNSCOPED_FAIL'):\n"
        "            print('remote catalog unavailable', file=sys.stderr)\n"
        "            raise SystemExit(1)\n"
        "    elif len(args) == 5 and args[:3] == ['plugin', 'list', '--marketplace'] and args[4] == '--json':\n"
        "        document = {**document, 'installed': [record for record in document['installed']\n"
        "                    if record.get('marketplaceName') == args[3]]}\n"
        "    else:\n"
        "        raise SystemExit('unsupported fake host arguments: ' + ' '.join(args))\n"
        "print(json.dumps(document))\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


def query_count(queries: Path, host: str) -> int:
    """The number of inventory queries, including Codex marketplace enumeration."""
    if not queries.is_file():
        return 0
    lines = queries.read_text(encoding="utf-8").splitlines()
    command = f"{host} plugin " + ("marketplace list --json" if host == "codex" else "list --json")
    return sum(line == command for line in lines)


def link_shared_runtime(data: Path) -> None:
    """Use the prepared runtime under the data root `data`; the store stays in `data`."""
    (data / "bootgear").mkdir(parents=True, exist_ok=True)
    (data / "bootgear" / "python").write_text(f"{sys.executable}\n")
    (data / "bootgear" / "runtimes").symlink_to(runtime.environment_path().parent,
                                                target_is_directory=True)
