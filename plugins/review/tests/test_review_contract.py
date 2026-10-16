import re
import unittest
from pathlib import Path

import yaml

PLUGIN_DIR = Path(__file__).resolve().parents[1]
SKILL_DIR = PLUGIN_DIR / "skills" / "review"
REFERENCES = SKILL_DIR / "references"
ANGLE_FILES = ("find-angles.yaml", "design-patterns.yaml")
ANGLE_KEYS = {"id", "tag", "tell", "asks", "lens", "cost"}
LENS_ANGLE_FILES = ("angles-security.yaml", "angles-tests.yaml", "angles-simplicity.yaml",
                    "angles-consistency.yaml")
PACK_FILES = ("pack-web.yaml", "pack-typed-oop.yaml", "pack-concurrency-db.yaml",
              "pack-test-tooling.yaml")
PROJECT_WORDS = ("kotlin", "java", "spring", "angular", "jpa", "hibernate", "flyway", "mockk",
                 "rxjs", "ngrx", "webclient", "jackson")


def _rows(name: str) -> list[dict]:
    return yaml.safe_load((REFERENCES / name).read_text())


def _full_depth_lenses() -> list[str]:
    skill = (SKILL_DIR / "SKILL.md").read_text()
    match = re.search(r"^- `full`: lenses `([^`]+)`", skill, re.MULTILINE)
    assert match, "SKILL.md has no `full` depth line"
    return match.group(1).split(",")


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

    def test_per_lens_files(self):
        found = sorted(path.name for path in REFERENCES.glob("angles-*.yaml"))
        self.assertEqual(found, sorted(LENS_ANGLE_FILES))
        for name in LENS_ANGLE_FILES:
            lens = name.removeprefix("angles-").removesuffix(".yaml")
            for row in _rows(name):
                self.assertLessEqual(set(row), ANGLE_KEYS, row)
                self.assertRegex(row["id"], r"\A[a-z0-9]+(-[a-z0-9]+)*\Z")
                self.assertEqual(row["tag"], "find", row)
                self.assertEqual(row["lens"], lens, row)

    def test_pack_files(self):
        found = sorted(path.name for path in REFERENCES.glob("pack-*.yaml"))
        self.assertEqual(found, sorted(PACK_FILES))
        for name in PACK_FILES:
            first_line = (REFERENCES / name).read_text().splitlines()[0]
            self.assertRegex(first_line, r"\A# use when: \S", name)
            for row in _rows(name):
                self.assertIn(row["lens"], _full_depth_lenses(), row)
                if row["lens"] == "architecture":
                    self.assertTrue(row["cost"].strip(), row)

    def test_ids_unique_across_angle_files(self):
        ids = [row["id"] for name in (*ANGLE_FILES, *LENS_ANGLE_FILES, *PACK_FILES)
               for row in _rows(name)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_angle_text_is_project_free(self):
        words = re.compile(r"\b(" + "|".join(PROJECT_WORDS) + r")\b", re.IGNORECASE)
        for name in (*LENS_ANGLE_FILES, *PACK_FILES):
            for row in _rows(name):
                for key in ("tell", "asks", "cost"):
                    self.assertIsNone(words.search(row.get(key, "")), (name, row["id"], key))


if __name__ == "__main__":
    unittest.main()
