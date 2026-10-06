import unittest
from pathlib import Path

import yaml

PLUGIN_DIR = Path(__file__).resolve().parents[1]
SKILL_DIR = PLUGIN_DIR / "skills" / "review"
REFERENCES = SKILL_DIR / "references"
ANGLE_FILES = ("find-angles.yaml", "design-patterns.yaml")
ANGLE_KEYS = {"id", "tag", "tell", "asks", "lens", "cost"}


class ReviewContractTest(unittest.TestCase):
    def test_angle_files_follow_converge_schema(self):
        ids = []
        for name in ANGLE_FILES:
            rows = yaml.safe_load((REFERENCES / name).read_text())
            self.assertIsInstance(rows, list, name)
            for row in rows:
                self.assertLessEqual(set(row), ANGLE_KEYS, row)
                self.assertRegex(row["id"], r"\A[a-z0-9]+(-[a-z0-9]+)*\Z")
                self.assertEqual(row["tag"], "find", row)
                self.assertTrue(row["tell"].strip(), row)
                self.assertTrue(row["asks"].strip(), row)
                if name == "design-patterns.yaml":
                    self.assertEqual(row["lens"], "architecture", row)
                    self.assertTrue(row["cost"].strip(), row)
                ids.append(row["id"])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(yaml.safe_load((REFERENCES / ANGLE_FILES[0]).read_text())), 12)
        self.assertEqual(len(yaml.safe_load((REFERENCES / ANGLE_FILES[1]).read_text())), 39)


if __name__ == "__main__":
    unittest.main()
