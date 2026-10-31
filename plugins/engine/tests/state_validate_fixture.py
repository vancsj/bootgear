"""Run `task state validate` on a scratch machine with one `clarify` node.

The node's reminder is `reminder_lines`. The node's `next` lists `nexts`; each
name other than `succeeded` gets a terminal-free stub node that goes to `succeeded`.
"""
import os
import subprocess
from pathlib import Path


def validate_reminder(tmp: Path, task_bin: Path, reminder_lines, nexts=("succeeded",)):
    path = tmp / "machine.yaml"
    extra = "".join(f"  {name}:\n    next: [succeeded]\n"
                    for name in nexts if name != "succeeded")
    path.write_text(
        "name: m\nnodes:\n  clarify:\n    reminder:\n"
        + "".join(f"      {line}\n" for line in reminder_lines)
        + f"    next: [{', '.join(nexts)}]\n" + extra
        + "  succeeded:\n    terminal: true\n  failed:\n    terminal: true\n")
    return subprocess.run([str(task_bin), "state", "validate", str(path)],
                          capture_output=True, text=True, check=False,
                          env={**os.environ, "BOOTGEAR_OUTPUT": "prose"})
