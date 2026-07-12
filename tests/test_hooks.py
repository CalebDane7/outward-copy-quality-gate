from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "outward-copy-quality-gate"
USER_HOOK = PLUGIN_ROOT / "hooks" / "user_prompt_submit.py"
STOP_HOOK = PLUGIN_ROOT / "hooks" / "stop_guard.py"
EXACT_PROMPT = (
    "Make the GitHub title more searchable with Windows LLM coding fixes skill WSL terms"
)


class HookContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.plugin_data = Path(self.temporary.name)
        self.env = os.environ.copy()
        self.env["PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        self.env["PLUGIN_DATA"] = str(self.plugin_data)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_hook(self, script: Path, event: dict) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
        )

    def prompt_event(self, turn_id: str = "turn-1", prompt: str = EXACT_PROMPT) -> dict:
        return {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-1",
            "turn_id": turn_id,
            "cwd": str(REPO_ROOT),
            "prompt": prompt,
        }

    def stop_event(
        self, message: str, turn_id: str = "turn-1", stop_hook_active: bool = False
    ) -> dict:
        return {
            "hook_event_name": "Stop",
            "session_id": "session-1",
            "turn_id": turn_id,
            "cwd": str(REPO_ROOT),
            "stop_hook_active": stop_hook_active,
            "last_assistant_message": message,
        }

    def open_turn(self, turn_id: str = "turn-1") -> dict:
        result = self.run_hook(USER_HOOK, self.prompt_event(turn_id=turn_id))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit"
        )
        return payload

    def marker_from_context(self, context: str) -> dict:
        match = re.search(
            r"<!--\s*outward-copy-quality-gate\s*:\s*(\{.*\})\s*-->", context
        )
        self.assertIsNotNone(match)
        return json.loads(match.group(1))

    def valid_marker(self, payload: dict) -> str:
        context = payload["hookSpecificOutput"]["additionalContext"]
        marker = self.marker_from_context(context)
        evidence = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "missing-one-gate.json").read_text()
        )["valid_evidence"]
        marker.update(evidence)
        return "<!-- outward-copy-quality-gate: " + json.dumps(
            marker, sort_keys=True, separators=(",", ":")
        ) + " -->"

    def test_exact_old_prompt_opens_private_hash_only_state(self) -> None:
        payload = self.open_turn()
        context = payload["hookSpecificOutput"]["additionalContext"]
        policy = json.loads(
            (PLUGIN_ROOT / "policy" / "outward-copy-policy.json").read_text()
        )
        previous_position = -1
        for entry in policy["skills"]:
            skill_path = (PLUGIN_ROOT / entry["path"]).resolve()
            path_line = f"Resolved SKILL.md path: {skill_path}"
            position = context.index(path_line)
            self.assertGreater(position, previous_position)
            previous_position = position
            self.assertIn(skill_path.read_text(encoding="utf-8").rstrip(), context)
        state_files = list((self.plugin_data / "turn-state").glob("*.json"))
        self.assertEqual(len(state_files), 1)
        stored = state_files[0].read_text()
        self.assertNotIn(EXACT_PROMPT, stored)
        self.assertNotIn(str(PLUGIN_ROOT), stored)
        self.assertIn("prompt_sha256", stored)

    def test_duplicate_catalog_skill_names_do_not_change_injected_material(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            duplicate_root = Path(temporary) / "skills"
            duplicate_id = "outward-copy-quality-gate-humanizer"
            duplicate = duplicate_root / duplicate_id / "SKILL.md"
            duplicate.parent.mkdir(parents=True)
            duplicate.write_text(
                "---\nname: outward-copy-quality-gate-humanizer\n"
                "description: Synthetic duplicate catalog fixture.\n---\n"
                "DUPLICATE-CATALOG-SENTINEL\n",
                encoding="utf-8",
            )
            self.env["CODEX_HOME"] = str(Path(temporary))
            payload = self.open_turn(turn_id="turn-duplicate-catalog")
            context = payload["hookSpecificOutput"]["additionalContext"]
            expected = (
                PLUGIN_ROOT / "skills" / duplicate_id / "SKILL.md"
            ).resolve()
            self.assertIn(f"Resolved SKILL.md path: {expected}", context)
            self.assertNotIn(str(duplicate.resolve()), context)
            self.assertNotIn("DUPLICATE-CATALOG-SENTINEL", context)

    def test_missing_unsafe_and_oversized_skill_content_fail_closed(self) -> None:
        for case in ("missing", "unsafe", "oversized"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                copied_root = Path(temporary) / "plugin"
                shutil.copytree(PLUGIN_ROOT, copied_root)
                skill_path = (
                    copied_root
                    / "skills"
                    / "outward-copy-quality-gate-router"
                    / "SKILL.md"
                )
                if case == "missing":
                    skill_path.unlink()
                elif case == "unsafe":
                    skill_path.write_text(
                        skill_path.read_text(encoding="utf-8")
                        + "\nSynthetic private path: "
                        + "/home/"
                        + "synthetic-user/project\n",
                        encoding="utf-8",
                    )
                else:
                    skill_path.write_bytes(b"x" * (32 * 1024 + 1))
                plugin_data = Path(temporary) / "plugin-data"
                env = os.environ.copy()
                env["PLUGIN_ROOT"] = str(copied_root)
                env["PLUGIN_DATA"] = str(plugin_data)
                result = subprocess.run(
                    [
                        sys.executable,
                        str(copied_root / "hooks" / "user_prompt_submit.py"),
                    ],
                    input=json.dumps(self.prompt_event(turn_id=f"turn-{case}")),
                    text=True,
                    capture_output=True,
                    env=env,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["decision"], "block")
                self.assertFalse((plugin_data / "turn-state").exists())

    def test_non_copy_prompt_is_noop(self) -> None:
        result = self.run_hook(
            USER_HOOK,
            self.prompt_event(prompt="What license is listed in the README?"),
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertFalse((self.plugin_data / "turn-state").exists())

    def test_stop_without_marker_requests_one_repair(self) -> None:
        self.open_turn()
        first = self.run_hook(STOP_HOOK, self.stop_event("Here is the new title."))
        first_payload = json.loads(first.stdout)
        self.assertEqual(first_payload["decision"], "block")
        self.assertNotIn(EXACT_PROMPT, first.stdout)

        second = self.run_hook(
            STOP_HOOK,
            self.stop_event("Still missing.", stop_hook_active=True),
        )
        self.assertEqual(json.loads(second.stdout), {})

    def test_stop_validates_repaired_marker_when_already_active(self) -> None:
        payload = self.open_turn()
        marker = self.valid_marker(payload)
        result = self.run_hook(
            STOP_HOOK,
            self.stop_event(
                "A clear searchable title.\n" + marker, stop_hook_active=True
            ),
        )
        self.assertEqual(json.loads(result.stdout), {})
        receipts = list((self.plugin_data / "receipts").glob("*.json"))
        self.assertEqual(len(receipts), 1)

    def test_valid_marker_writes_hash_bound_receipt_without_copy(self) -> None:
        payload = self.open_turn()
        copy = "Windows PowerShell, WSL, and SSH fixes for AI coding agents"
        final_message = copy + "\n" + self.valid_marker(payload)
        result = self.run_hook(
            STOP_HOOK, self.stop_event(final_message)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})
        receipts = list((self.plugin_data / "receipts").glob("*.json"))
        self.assertEqual(len(receipts), 1)
        receipt_text = receipts[0].read_text()
        self.assertNotIn(EXACT_PROMPT, receipt_text)
        self.assertNotIn(copy, receipt_text)
        receipt = json.loads(receipt_text)
        self.assertEqual(receipt["status"], "validated")
        self.assertEqual(
            receipt["scopes"],
            ["title_headline", "seo_search", "repository_metadata"],
        )
        message_path = self.plugin_data / "final-message.txt"
        message_path.write_text(final_message, encoding="utf-8")
        validator = subprocess.run(
            [
                sys.executable,
                str(PLUGIN_ROOT / "scripts" / "validate_receipt.py"),
                "--receipt",
                str(receipts[0]),
                "--message-file",
                str(message_path),
            ],
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(validator.returncode, 0, validator.stdout + validator.stderr)
        self.assertEqual(json.loads(validator.stdout)["status"], "pass")

    def test_each_missing_gate_blocks(self) -> None:
        fixture = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "missing-one-gate.json").read_text()
        )
        for index, case in enumerate(fixture["missing_one_gate"]):
            with self.subTest(case["id"]):
                turn_id = f"turn-missing-{index}"
                payload = self.open_turn(turn_id=turn_id)
                context = payload["hookSpecificOutput"]["additionalContext"]
                marker = self.marker_from_context(context)
                marker.update(fixture["valid_evidence"])
                marker.pop(case["omit"])
                comment = "<!-- outward-copy-quality-gate: " + json.dumps(
                    marker, sort_keys=True, separators=(",", ":")
                ) + " -->"
                result = self.run_hook(
                    STOP_HOOK,
                    self.stop_event("Candidate.\n" + comment, turn_id=turn_id),
                )
                response = json.loads(result.stdout)
                self.assertEqual(response["decision"], "block")
                expected_label = {
                    "copy_owner_evidence": "copy-owner",
                    "humanizer_evidence": "Humanizer",
                    "ogilvy_evidence": "Ogilvy",
                }[case["omit"]]
                self.assertIn(expected_label, response["reason"])

    def test_stale_skill_hash_blocks(self) -> None:
        payload = self.open_turn()
        context = payload["hookSpecificOutput"]["additionalContext"]
        marker = self.marker_from_context(context)
        marker.update(
            json.loads(
                (REPO_ROOT / "tests" / "fixtures" / "missing-one-gate.json").read_text()
            )["valid_evidence"]
        )
        marker["humanizer_skill_sha256"] = "0" * 64
        comment = "<!-- outward-copy-quality-gate: " + json.dumps(
            marker, sort_keys=True, separators=(",", ":")
        ) + " -->"
        result = self.run_hook(STOP_HOOK, self.stop_event("Candidate.\n" + comment))
        self.assertEqual(json.loads(result.stdout)["decision"], "block")


if __name__ == "__main__":
    unittest.main()
