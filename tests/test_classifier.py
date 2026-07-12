from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "outward-copy-quality-gate"
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))

from gate_core import classify_prompt  # noqa: E402


class ClassifierFixtureTests(unittest.TestCase):
    def test_positive_fixtures(self) -> None:
        fixtures = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "classifier-positive.json").read_text()
        )
        for fixture in fixtures:
            with self.subTest(fixture["id"]):
                self.assertEqual(classify_prompt(fixture["prompt"]), fixture["scopes"])

    def test_negative_fixtures(self) -> None:
        fixtures = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "classifier-negative.json").read_text()
        )
        for fixture in fixtures:
            with self.subTest(fixture["id"]):
                self.assertEqual(classify_prompt(fixture["prompt"]), [])

    def test_empty_and_non_string_input_is_safe(self) -> None:
        self.assertEqual(classify_prompt(""), [])
        self.assertEqual(classify_prompt("   "), [])
        self.assertEqual(classify_prompt(None), [])  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
