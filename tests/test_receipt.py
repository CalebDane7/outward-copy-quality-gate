from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "outward-copy-quality-gate"
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))

from gate_core import (  # noqa: E402
    RECEIPT_REQUIRED_FIELDS,
    load_policy,
    skill_records,
    validate_receipt_shape,
)


class ReceiptShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy, _ = load_policy(PLUGIN_ROOT)
        self.skills = skill_records(PLUGIN_ROOT, self.policy)
        self.receipt = {
            "schema": self.policy["receipt_schema"],
            "policy_id": self.policy["policy_id"],
            "plugin_version": self.policy["plugin_version"],
            "status": "validated",
            "turn_key": "1" * 64,
            "prompt_sha256": "2" * 64,
            "output_sha256": "3" * 64,
            "policy_sha256": "4" * 64,
            "scopes": ["readme"],
            "copy_owner_evidence": "owner:assigned-agent",
            "humanizer_evidence": "humanizer:plain-read",
            "ogilvy_evidence": "ogilvy:benefit-proof",
            "skills": self.skills,
            "created_at": "2026-07-13T00:00:00+00:00",
            "validated_at": "2026-07-13T00:00:01+00:00",
        }

    def test_valid_receipt_shape(self) -> None:
        self.assertEqual(set(self.receipt), RECEIPT_REQUIRED_FIELDS)
        self.assertEqual(
            validate_receipt_shape(self.receipt, self.policy, self.skills), []
        )

    def test_each_missing_gate_fails(self) -> None:
        fixture = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "missing-one-gate.json").read_text()
        )
        for case in fixture["missing_one_gate"]:
            with self.subTest(case["id"]):
                candidate = dict(self.receipt)
                candidate.pop(case["omit"])
                errors = validate_receipt_shape(candidate, self.policy, self.skills)
                self.assertTrue(errors)

    def test_wrong_evidence_prefix_fails(self) -> None:
        self.receipt["humanizer_evidence"] = "owner:wrong-stage"
        errors = validate_receipt_shape(self.receipt, self.policy, self.skills)
        self.assertIn("humanizer_evidence_invalid", errors)

    def test_stale_skill_record_fails(self) -> None:
        self.receipt["skills"] = [dict(item) for item in self.skills]
        self.receipt["skills"][0]["sha256"] = "0" * 64
        errors = validate_receipt_shape(self.receipt, self.policy, self.skills)
        self.assertIn("skills_invalid", errors)


if __name__ == "__main__":
    unittest.main()
