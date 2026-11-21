import sys
from importlib import import_module
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "plugins" / "engine"
sys.path.insert(0, str(PLUGIN_DIR / "src"))

host_adapter = import_module("engine.host_adapter")
policy = import_module("engine.policy")
state_nudge = import_module("engine.policy_state_nudge")
session_paths = import_module("engine.session_paths")
AdapterError = host_adapter.AdapterError
HostContext = host_adapter.HostContext
normalize_event = host_adapter.normalize_event

RUNNER = Path(__file__).resolve().parent / "run_host_adapter_fixture.py"
