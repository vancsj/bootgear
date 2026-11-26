import subprocess
import sys
from pathlib import Path

import pytest

VALIDATOR = Path(__file__).resolve().parents[1] / "src" / "engine" / "validate_standard.py"


@pytest.mark.parametrize(
    "comment",
    ["<!-- Editorial note. -->", "<!-- Editorial note.\nAdd rule prose here. -->"],
    ids=["single-line", "multiline"],
)
def test_html_comment_does_not_count_as_rule_prose(tmp_path: Path, comment: str) -> None:
    standard = tmp_path / "example-standard.md"
    standard.write_text(
        "severities: [must]\ncutoff: must\n\n"
        "## R001 [must]\n"
        f"{comment}\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(standard)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "rule 'R001' has no prose beneath its heading" in result.stdout
