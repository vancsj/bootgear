"""Start Gear from the CLI plugin's source."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from bootgear_cli.gear import entrypoint

entrypoint()
