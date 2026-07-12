from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "outward-copy-quality-gate"


class IsolatedPackageProof(unittest.TestCase):
    def test_versioned_cache_copy_has_no_source_machine_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            isolated_root = Path(temporary) / "marketplace"
            # WHY: Codex caches the complete public subtree; filtering ignored
            # files here would hide the exact bytecode leak this proof must catch.
            shutil.copytree(REPO_ROOT, isolated_root)
            marketplace_plugin = isolated_root / "plugins" / PLUGIN_NAME
            manifest = json.loads(
                (marketplace_plugin / ".codex-plugin" / "plugin.json").read_text()
            )
            self.assertEqual(manifest["version"], "0.1.1")
            plugin_root = (
                Path(temporary)
                / "codex-cache"
                / PLUGIN_NAME
                / manifest["version"]
            )
            shutil.copytree(marketplace_plugin, plugin_root)
            plugin_data = Path(temporary) / "plugin-data"
            env = os.environ.copy()
            env["PLUGIN_ROOT"] = str(plugin_root)
            env["PLUGIN_DATA"] = str(plugin_data)

            package_check = subprocess.run(
                [
                    sys.executable,
                    str(marketplace_plugin / "scripts" / "validate_package.py"),
                    "--repo-root",
                    str(isolated_root),
                ],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(
                package_check.returncode, 0, package_check.stdout + package_check.stderr
            )

            event = {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "isolated-session",
                "turn_id": "isolated-turn",
                "cwd": str(isolated_root),
                "prompt": "Make the GitHub title more searchable with Windows LLM coding fixes skill WSL terms",
            }
            prompt_result = subprocess.run(
                [sys.executable, str(plugin_root / "hooks" / "user_prompt_submit.py")],
                input=json.dumps(event),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(prompt_result.returncode, 0, prompt_result.stderr)
            payload = json.loads(prompt_result.stdout)
            self.assertEqual(
                payload["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit"
            )
            context = payload["hookSpecificOutput"]["additionalContext"]
            policy = json.loads(
                (plugin_root / "policy" / "outward-copy-policy.json").read_text()
            )
            for entry in policy["skills"]:
                cached_skill = (plugin_root / entry["path"]).resolve()
                self.assertIn(f"Resolved SKILL.md path: {cached_skill}", context)
                self.assertIn(
                    cached_skill.read_text(encoding="utf-8").rstrip(), context
                )
            self.assertNotIn(str(marketplace_plugin.resolve()), context)

            stop_event = {
                "hook_event_name": "Stop",
                "session_id": "isolated-session",
                "turn_id": "isolated-turn",
                "cwd": str(isolated_root),
                "stop_hook_active": False,
                "last_assistant_message": "Unreviewed public title",
            }
            stop_result = subprocess.run(
                [sys.executable, str(plugin_root / "hooks" / "stop_guard.py")],
                input=json.dumps(stop_event),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(stop_result.returncode, 0, stop_result.stderr)
            self.assertEqual(json.loads(stop_result.stdout)["decision"], "block")


if __name__ == "__main__":
    unittest.main()
