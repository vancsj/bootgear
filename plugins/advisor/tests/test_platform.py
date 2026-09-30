from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

CHANNEL_DIR = Path(__file__).resolve().parents[1] / "skills" / "advisor" / "scripts"

sys.path.insert(0, str(CHANNEL_DIR))
import channel as channel_module  # pyright: ignore[reportMissingImports]


class UnsupportedPlatformTest(unittest.TestCase):
    def test_non_macos_start_time_read_fails_with_a_named_category(self) -> None:
        stderr = io.StringIO()
        with mock.patch.object(sys, "platform", "linux"), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                channel_module.read_process_start_time(os.getpid())
        self.assertEqual(raised.exception.code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["category"], "unsupported_platform")
        self.assertIn("macOS", payload["error"])


if __name__ == "__main__":
    unittest.main()
