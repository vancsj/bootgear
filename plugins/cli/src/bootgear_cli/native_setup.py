"""Install, repair, and configure Bootgear through the selected host."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from bootgear_cli import clikit, hook_loader, runtime
from bootgear_cli.native_process import SetupError, run

MARKETPLACE = "bootgear"
OFFICIAL = "https://github.com/vancsj/bootgear.git"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
LAUNCH = (
    'launcher="$(mktemp)" && curl -fsSL --max-time 120 '
    'https://raw.githubusercontent.com/vancsj/bootgear/main/setup-macos.sh -o "$launcher" '
    '&& /bin/bash "$launcher"'
)
CATALOGS = {"claude": ".claude-plugin/marketplace.json", "codex": ".agents/plugins/marketplace.json"}
DEFAULTS = {
    "converge": {"converge.yaml": "{}\n"},
    "engine": {
        "converge-seats.yaml": (
            "seats:\n  main: native_subagent\n  finder: native_subagent\n"
            "  r1: native_subagent\n  r2: native_subagent\n  cutter: native_subagent\n"
        ),
        "debate-parties.yaml": (
            "parties:\n  independent-reviewer:\n    mechanism: native_subagent\n  adversarial-reviewer: {}\n"
        ),
    },
}


@dataclass(frozen=True)
class Catalog:
    root: Path
    local: bool


@dataclass(frozen=True)
class Package:
    name: str
    root: Path
    version: str
    dependencies: tuple[str, ...]


def _json_file(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SetupError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SetupError(f"Expected an object in {path}.")
    return value


def _catalog_entries(catalog: Catalog, host: str) -> dict[str, dict]:
    path = catalog.root / CATALOGS[host]
    document = _json_file(path)
    entries = document.get("plugins")
    if document.get("name") != MARKETPLACE or not isinstance(entries, list):
        raise SetupError(f"Invalid Bootgear catalog at {path}.")
    by_name = {}
    for entry in entries:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in by_name:
            raise SetupError(f"Invalid or duplicate plugin name in {path}: {name!r}.")
        by_name[name] = entry
    return by_name


def _package(catalog: Catalog, name: str, entry: dict) -> Package:
    source = entry.get("source")
    if isinstance(source, dict) and source.get("source") == "local":
        source = source.get("path")
    if not isinstance(source, str) or Path(source).is_absolute():
        raise SetupError(f"Invalid source for {name} in {catalog.root}.")
    root = (catalog.root / source).resolve()
    if not root.is_relative_to(catalog.root):
        raise SetupError(f"Source for {name} points outside the Bootgear catalog.")
    manifest = _json_file(root / ".claude-plugin/plugin.json")
    version, dependencies = manifest.get("version"), manifest.get("dependencies", [])
    if (manifest.get("name") != name or not isinstance(version, str)
            or not isinstance(dependencies, list)
            or any(not isinstance(dep, str) or not NAME.fullmatch(dep) for dep in dependencies)):
        raise SetupError(f"Invalid manifest for {name} at {root}.")
    return Package(name, root, version, tuple(dependencies))


def _closure(catalog: Catalog, host: str, targets: tuple[str, ...]) -> dict[str, Package]:
    entries = _catalog_entries(catalog, host)
    unknown = [name for name in targets if name not in entries]
    if unknown:
        raise SetupError(f"Unknown Bootgear plugins: {', '.join(unknown)}. Check the names and retry.")
    packages = {}

    def add(name: str) -> None:
        if name in packages:
            return
        if name not in entries:
            raise SetupError(f"Required plugin {name} is absent from the Bootgear catalog.")
        package = packages[name] = _package(catalog, name, entries[name])
        for dependency in package.dependencies:
            add(dependency)

    for target in targets:
        add(target)
    return packages


def _official(source: object) -> bool:
    return isinstance(source, str) and source in {
        OFFICIAL, OFFICIAL.removesuffix(".git"), "vancsj/bootgear",
        "git@github.com:vancsj/bootgear.git", "ssh://git@github.com/vancsj/bootgear.git",
    }


class Setup:
    def __init__(self, host: str, caller: Path, source: Path | None, local: bool):
        self.host = host
        self.caller = caller
        self.source = source
        self.local = local
        self.profile = hook_loader.profile_root(host)
        self.env = os.environ.copy()
        self.env["CODEX_HOME" if host == "codex" else "CLAUDE_CONFIG_DIR"] = str(self.profile)
        if host == "claude":
            self.env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"

    def _native(self, *arguments: str) -> object:
        output = run([self.host, "plugin", *arguments, "--json"], cwd=self.caller, env=self.env)
        try:
            return json.loads(output)
        except ValueError:
            try:
                return json.loads(output.strip().splitlines()[-1])
            except (IndexError, ValueError) as exc:
                raise SetupError(f"{self.host} plugin {' '.join(arguments)} returned invalid JSON.") from exc

    def registered(self) -> Catalog | None:
        if not self.profile.exists():
            return None
        response = self._native("marketplace", "list")
        records = response if self.host == "claude" else (
            response.get("marketplaces") if isinstance(response, dict) else None)
        if not isinstance(records, list):
            raise SetupError(f"{self.host} returned an invalid marketplace list.")
        matches = [record for record in records if isinstance(record, dict) and record.get("name") == MARKETPLACE]
        if not matches:
            return None
        if len(matches) != 1:
            raise SetupError(f"{self.host} returned more than one Bootgear marketplace.")
        record = matches[0]
        if self.host == "claude":
            kind, root = record.get("source"), record.get("installLocation")
            origin = record.get("url") or record.get("repo") or record.get("path")
        else:
            details = record.get("marketplaceSource") or {}
            kind, root = details.get("sourceType"), record.get("root")
            origin = details.get("source")
        local = kind in {"directory", "local", "path"}
        valid = _official(origin) and not self.local
        if local and isinstance(root, str) and isinstance(origin, str):
            local_root = Path(root).expanduser().resolve()
            valid = local_root == Path(origin).expanduser().resolve() and (
                self.source is None or (self.local and local_root == self.source)
            )
        if not valid or not isinstance(root, str):
            raise SetupError(f"The registered Bootgear marketplace points to {origin or root!r}. Select its source or correct it in {self.host}.")
        return Catalog(Path(root).expanduser().resolve(), local)

    def _register(self) -> Catalog:
        self.profile.mkdir(parents=True, exist_ok=True)
        origin = str(self.source) if self.local else OFFICIAL
        self._native("marketplace", "add", origin)
        catalog = self.registered()
        if not catalog:
            raise SetupError("Bootgear marketplace registration is missing. Retry Install.")
        return catalog

    def choices(self) -> list[dict[str, str]]:
        catalog = self.registered()
        if not catalog:
            if self.source is None:
                raise SetupError(f"Open Bootgear Setup to register the marketplace.\n{LAUNCH}")
            catalog = Catalog(self.source, self.local)
        return [{"name": name, "description": str(entry.get("description", ""))}
                for name, entry in _catalog_entries(catalog, self.host).items()]

    def _records(self, catalog: Catalog) -> list[dict]:
        if self.host == "codex":
            response = self._native("list", "--marketplace", MARKETPLACE)
            records = response.get("installed") if isinstance(response, dict) else None
        else:
            records = self._native("list")
        if not isinstance(records, list):
            raise SetupError(f"{self.host} returned an invalid plugin list.")
        selected = []
        for record in records:
            if not isinstance(record, dict):
                continue
            if self.host == "codex":
                if record.get("marketplaceName") != MARKETPLACE or not record.get("installed", True):
                    continue
                root = hook_loader.codex_cache_root(record)
                name = record.get("name")
            else:
                identity = record.get("id")
                if not isinstance(identity, str) or not identity.endswith(f"@{MARKETPLACE}"):
                    continue
                if not hook_loader.applies_to(record, self.caller):
                    continue
                name = identity.removesuffix(f"@{MARKETPLACE}")
                path = record.get("installPath")
                root = Path(path) if isinstance(path, str) else None
                if catalog.local and name in (entries := _catalog_entries(catalog, self.host)):
                    root = _package(catalog, name, entries[name]).root
            if isinstance(name, str):
                selected.append({**record, "name": name, "root": root})
        return selected

    @staticmethod
    def _effective(records: list[dict]) -> dict[str, dict]:
        result = {}
        for record in records:
            result.setdefault(record["name"], record)
        return result

    def _configured(self, records: list[dict]) -> dict[str, bool]:
        configured = {name: bool(record.get("enabled")) for name, record in self._effective(records).items()}
        path = self.profile / "config.toml"
        if self.host == "codex" and path.is_file():
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            for identity, value in data.get("plugins", {}).items():
                if identity.endswith(f"@{MARKETPLACE}") and isinstance(value, dict):
                    configured.setdefault(identity.removesuffix(f"@{MARKETPLACE}"), bool(value.get("enabled", True)))
        return configured

    def _update(self, name: str, record: dict | None) -> None:
        identity = f"{name}@{MARKETPLACE}"
        if self.host == "codex":
            self._native("add", identity)
        elif record is None:
            self._native("install", identity, "--scope", "user")
        else:
            self._native("update", identity, "--scope", (record.get("scope") or "user"))

    @staticmethod
    def _usable(package: Package, record: dict | None) -> bool:
        if record is None or not isinstance(root := record.get("root"), Path):
            return False
        manifest = root / ".claude-plugin/plugin.json"
        if not manifest.is_file():
            return False
        try:
            data = _json_file(manifest)
        except SetupError:
            return False
        return data.get("name") == package.name and data.get("version") == package.version

    def _refresh(self, catalog: Catalog, records: list[dict]) -> Catalog:
        if not catalog.local:
            command = "upgrade" if self.host == "codex" else "update"
            result = self._native("marketplace", command, MARKETPLACE)
            if isinstance(result, dict) and result.get("errors"):
                raise SetupError(f"Marketplace refresh failed: {result['errors']}")
            refreshed = self.registered()
            if refreshed is None:
                raise SetupError("Bootgear marketplace disappeared after refresh. Retry Repair.")
            catalog = refreshed
        if self.host == "claude":
            for record in records:
                self._update(record["name"], record)
        return catalog

    def packages(self, operation: str, selected: tuple[str, ...]) -> tuple[dict[str, dict], set[str], list[str]]:
        catalog = self.registered()
        full = operation == "repair" and not selected
        targets = selected or ("cli",)
        if not catalog:
            if operation != "install" or self.source is None:
                raise SetupError(f"Bootgear has no verified marketplace. Open Bootgear Setup and choose Install.\n{LAUNCH}")
            _closure(Catalog(self.source, self.local), self.host, targets)
            catalog = self._register()
        records = self._records(catalog)
        configured = self._configured(records)
        pending = []
        if full:
            if not configured:
                raise SetupError("There are no Bootgear plugins to repair. Choose Install first.")
            catalog = self._refresh(catalog, records)
            targets = tuple(name for name, enabled in configured.items() if enabled)
            records = self._records(catalog)
        packages = _closure(catalog, self.host, targets)
        changeable = {name: package for name, package in packages.items()
                      if not (full and name == "cli" and configured.get(name) is False)}
        original = self._effective(records)
        for name in changeable:
            record = original.get(name)
            if record and not record.get("enabled"):
                if full:
                    raise SetupError(f"Enable the required plugin {name}@{MARKETPLACE} in {self.host}, then retry.")
                raise SetupError(f"Enable {name}@{MARKETPLACE} in {self.host}, then retry.")
        for name, package in changeable.items():
            current = self._effective(records).get(name)
            if self._usable(package, current):
                continue
            if operation == "configure":
                raise SetupError(f"Run Install or Repair for {name}@{MARKETPLACE}, then retry Configure.")
            self._update(name, current)
            records = self._records(catalog)
            current = self._effective(records).get(name)
            if not current or not current.get("enabled") or not self._usable(package, current):
                raise SetupError(f"{name}@{MARKETPLACE} is unavailable at {package.version}. Retry with native {self.host} Repair.")
        effective = self._effective(records)
        if full:
            entries = _catalog_entries(catalog, self.host)
            for name, enabled in configured.items():
                record = effective.get(name)
                if name not in entries or (record and bool(record.get("enabled")) != enabled):
                    raise SetupError(f"Repair changed the availability of {name}@{MARKETPLACE}. Check it in {self.host}.")
                if not self._usable(_package(catalog, name, entries[name]), record):
                    if enabled:
                        raise SetupError(f"Repair could not restore {name}@{MARKETPLACE}. Retry Repair.")
                    pending.append(f"Enable {name}@{MARKETPLACE} in {self.host} to update its bundle.")
        return effective, set(packages), pending


def seed_defaults(profile: Path, plugins: set[str]) -> list[str]:
    created = []
    for plugin in sorted(plugins):
        for name, text in DEFAULTS.get(plugin, {}).items():
            profile.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = profile / name
            if path.exists():
                continue
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=profile, delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    stream.write(text)
                    stream.close()
                    os.link(temporary, path)
                except FileExistsError:
                    continue
                finally:
                    temporary.unlink(missing_ok=True)
            created.append(str(path))
    return created


def _installer(host: str) -> Setup:
    source = os.environ.get("BOOTGEAR_SETUP_SOURCE")
    selected = Path(source).resolve() if source else None
    local = os.environ.get("BOOTGEAR_SETUP_LOCAL") == "1"
    if not source:
        checkout = Path(os.environ.get("GEAR_ROOT") or runtime.CLI_ROOT)
        if (checkout / CATALOGS[host]).is_file():
            selected, local = checkout.resolve(), True
    if shutil.which(host) is None:
        raise SetupError(f"{host} is missing. Install the host CLI, then retry setup.")
    return Setup(host, clikit.caller_cwd(), selected, local)


def execute_setup(host: str, operation: str, selected: tuple[str, ...]) -> dict:
    if os.environ.get("BOOTGEAR_HOOK_ACTIVE") == "1":
        raise SetupError("Run setup outside the hook, then retry.")
    installer = _installer(host)
    with runtime.setup_lock():
        installed, closure, pending = installer.packages(operation, selected)
        cli = installed.get("cli", {})
        root = cli.get("root")
        if not isinstance(root, Path) or not (root / "uv.lock").is_file():
            raise SetupError("The verified CLI runtime is missing. Choose Install and select cli.")
        environment = runtime.setup(root, repair=operation == "repair")
        ready = {name for name in closure if name in installed and installed[name].get("enabled")}
        created = seed_defaults(installer.profile, ready)
        inventory = hook_loader.query_inventory(host, installer.caller)
        hook_loader.write_profile_inventory(host, installer.caller, inventory)
        interpreter = runtime.record_interpreter()
    if not cli.get("enabled"):
        pending.append(f"Enable cli@{MARKETPLACE} in {host} to load Gear hooks.")
    trust = ("Review and trust new or changed hooks in /hooks." if host == "codex"
             else "Review any Claude Code workspace trust prompt when reopening the project.")
    return {"runtime": str(environment), "python": str(interpreter), "selected": list(selected),
            "plugins": sorted(ready), "defaults": created, "pending": pending,
            "activation": "unverified", "next": f"Restart your Claude Code or Codex sessions. {trust}"}


def main() -> int:
    program = clikit.current_program("cli", "setup")
    parser = runtime.SetupParser(prog=program, description=__doc__, epilog=f"example: {program} --plugin engine")
    parser.add_argument("--operation", choices=("install", "repair", "configure"), default="install")
    parser.add_argument("--plugin", action="append", default=[], help="Bootgear plugin name; repeat for more choices")
    parser.add_argument("--gui", action="store_true", help="Open the macOS setup window")
    flags = parser.add_mutually_exclusive_group()
    flags.add_argument("--json", action="store_true")
    flags.add_argument("--prose", action="store_true")
    args = parser.parse_args()
    if args.gui:
        from bootgear_cli.setup_window import launch

        return launch()
    mode = clikit.resolve_mode(args.json, args.prose)
    host = clikit.host()
    try:
        if host not in {"claude", "codex"}:
            raise SetupError("Select a host with Gear --host claude or --host codex, then retry setup.")
        result = execute_setup(host, args.operation, tuple(dict.fromkeys(args.plugin)))
    except (OSError, ValueError, RuntimeError, SetupError, runtime.RuntimeNotReady) as exc:
        error = json.dumps({"error": str(exc)}) if mode == "json" else f"gear: {exc}"
        print(error, file=sys.stderr)
        return 2
    steps = [f"Managed Python: {result['python']}", f"Shared runtime ready: {result['runtime']}",
             f"Selected: {', '.join(result['selected']) or 'none'}",
             f"Plugins ready: {', '.join(result['plugins']) or 'none'}", *result["pending"]]
    clikit.emit(mode, result, steps, next=result["next"])
    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda signum, _frame: sys.exit(128 + signum))
    sys.exit(main())
