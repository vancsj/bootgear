from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from bootgear_cli import hook_loader

WORKER = """
import json, os, sys, time
from pathlib import Path
from bootgear_cli import hook_loader

base, host = Path(sys.argv[1]), sys.argv[2]
(base / ('reader-' + str(os.getpid()))).touch()

inventory = {'installed': []} if host == 'codex' else []
def query(*args):
    with (base / 'queries').open('a') as stream:
        stream.write(str(os.getpid()) + '\\n')
    deadline = time.monotonic() + 15
    while not (base / 'release').exists():
        if time.monotonic() > deadline:
            raise RuntimeError('inventory query was not released')
        time.sleep(.01)
    return inventory
hook_loader._codex_inventory = query
hook_loader._query_inventory = query
session = os.environ.get('INVENTORY_TEST_SESSION', 'same-session')
if 'read' in sys.argv:
    print(json.dumps(hook_loader.host_inventory(host, session)[0]))
else:
    source = 'resume' if 'refresh' in sys.argv else 'startup'
    with hook_loader.session_start_inventory(host, session, base, source) as result:
        print(json.dumps(result))
"""


class InventoryConcurrencyTests(unittest.TestCase):
    def test_different_sessions_load_inventory_concurrently(self) -> None:
        for host in ('codex', 'claude'):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as folder:
                base = Path(folder)
                env = {**os.environ, 'XDG_DATA_HOME': str(base / 'data')}
                env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
                workers = [subprocess.Popen(
                    [sys.executable, '-c', WORKER, str(base), host],
                    env={**env, 'INVENTORY_TEST_SESSION': session}, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                ) for session in ('first', 'second')]
                try:
                    deadline = time.monotonic() + 10
                    while not (base / 'queries').exists() or len((base / 'queries').read_text().splitlines()) < 2:
                        if time.monotonic() > deadline:
                            self.fail('independent sessions blocked each other')
                        time.sleep(.01)
                    (base / 'release').touch()
                    for worker in workers:
                        _, stderr = worker.communicate(timeout=10)
                        self.assertEqual(worker.returncode, 0, stderr)
                finally:
                    for worker in workers:
                        if worker.poll() is None:
                            worker.kill()
                        worker.communicate()

    def test_resume_invalidates_inventory_before_query_without_locking_readers(self) -> None:
        for host in ('codex', 'claude'):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as folder:
                base = Path(folder)
                env = {**os.environ, 'XDG_DATA_HOME': str(base / 'data')}
                env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
                old_inventory = {'installed': [{'name': 'old'}]} if host == 'codex' else [{'id': 'old'}]
                with patch.dict(os.environ, env):
                    cache = hook_loader.store_path(host, "same-session")
                    hook_loader._write_entry(cache, old_inventory, base)
                command = [sys.executable, '-c', WORKER, str(base), host]
                refresh = subprocess.Popen(
                    [*command, 'refresh'], env=env, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                try:
                    deadline = time.monotonic() + 10
                    while not (base / 'queries').exists():
                        if refresh.poll() is not None:
                            self.fail(refresh.communicate()[1])
                        if time.monotonic() > deadline:
                            self.fail('refresh did not reach the inventory query')
                        time.sleep(.01)
                    cached = subprocess.run([*command, "read"], env=env, capture_output=True, text=True, timeout=5, check=False)
                    self.assertNotEqual(cached.returncode, 0, cached.stderr)
                    self.assertIn("fresh host session", cached.stderr)
                    (base / 'release').touch()
                    stdout, stderr = refresh.communicate(timeout=10)
                    self.assertEqual(refresh.returncode, 0, stderr)
                    expected = {'installed': []} if host == 'codex' else []
                    self.assertEqual(json.loads(stdout), expected)
                    self.assertEqual(json.loads(cache.read_text())['inventory'], expected)
                finally:
                    if refresh.poll() is None:
                        refresh.kill()
                    refresh.communicate()

    def test_concurrent_cold_readers_share_one_inventory_query(self) -> None:
        for host in ('codex', 'claude'):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as folder:
                base = Path(folder)
                env = {**os.environ, 'XDG_DATA_HOME': str(base / 'data')}
                env['PYTHONPATH'] = os.pathsep.join((
                    str(Path(__file__).resolve().parents[1] / 'src'),
                    env.get('PYTHONPATH', ''),
                ))
                workers = [subprocess.Popen(
                    [sys.executable, '-c', WORKER, str(base), host],
                    env=env, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                ) for _ in range(6)]
                try:
                    deadline = time.monotonic() + 10
                    while len(list(base.glob('reader-*'))) < len(workers):
                        for worker in workers:
                            if worker.poll() is not None:
                                self.fail(worker.communicate()[1])
                        if time.monotonic() > deadline:
                            self.fail('not all workers reached the cache read')
                        time.sleep(.01)
                    (base / 'release').touch()
                    expected = {'installed': []} if host == 'codex' else []
                    for worker in workers:
                        stdout, stderr = worker.communicate(timeout=20)
                        self.assertEqual(worker.returncode, 0, stderr)
                        self.assertEqual(json.loads(stdout), expected)
                    self.assertEqual(len((base / 'queries').read_text().splitlines()), 1)
                finally:
                    for worker in workers:
                        if worker.poll() is None:
                            worker.kill()
                        worker.communicate()
