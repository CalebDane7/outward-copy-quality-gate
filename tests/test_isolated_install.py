from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "outward-copy-quality-gate"


class IsolatedPackageProof(unittest.TestCase):
    def test_versioned_cache_copy_routes_without_source_or_stop_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            isolated_marketplace = temporary_root / "marketplace"
            shutil.copytree(REPO_ROOT, isolated_marketplace)
            marketplace_plugin = isolated_marketplace / "plugins" / PLUGIN_NAME
            manifest = json.loads(
                (marketplace_plugin / ".codex-plugin" / "plugin.json").read_text()
            )
            self.assertEqual(manifest["version"], "0.2.0")

            plugin_root = (
                temporary_root
                / "codex-cache"
                / PLUGIN_NAME
                / PLUGIN_NAME
                / manifest["version"]
            )
            shutil.copytree(marketplace_plugin, plugin_root)
            env = os.environ.copy()
            env["PLUGIN_ROOT"] = str(plugin_root)
            env["PLUGIN_DATA"] = str(temporary_root / "plugin-data")
            env["PYTHONDONTWRITEBYTECODE"] = "1"

            package_check = subprocess.run(
                [
                    os.environ.get("PYTHON", "python3"),
                    str(marketplace_plugin / "scripts" / "validate_package.py"),
                    "--repo-root",
                    str(isolated_marketplace),
                ],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(
                package_check.returncode,
                0,
                package_check.stdout + package_check.stderr,
            )

            hooks = json.loads((plugin_root / "hooks" / "hooks.json").read_text())
            self.assertEqual(set(hooks["hooks"]), {"UserPromptSubmit"})
            command = hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
            event = {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "isolated-session",
                "turn_id": "isolated-turn",
                "cwd": str(isolated_marketplace),
                "prompt": "Make the GitHub title more searchable with Windows LLM coding fixes skill WSL terms",
            }
            result = subprocess.run(
                command,
                shell=True,
                executable="/bin/sh",
                input=json.dumps(event),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertNotEqual(payload.get("decision"), "block")
            context = payload["hookSpecificOutput"]["additionalContext"]
            policy = json.loads(
                (plugin_root / "policy" / "outward-copy-policy.json").read_text()
            )
            for entry in policy["skills"]:
                cached_skill = (plugin_root / entry["path"]).resolve()
                self.assertIn(f"Resolved SKILL.md path: {cached_skill}", context)
                self.assertIn(cached_skill.read_text().rstrip(), context)
            self.assertNotIn(str(marketplace_plugin.resolve()), context)
            self.assertFalse(Path(env["PLUGIN_DATA"]).exists())
            self.assertFalse((plugin_root / "hooks" / "stop_guard.py").exists())
            self.assertFalse((plugin_root / "schemas" / "receipt.schema.json").exists())


if __name__ == "__main__":
    unittest.main()
