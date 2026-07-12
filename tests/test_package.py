from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "outward-copy-quality-gate"


class PackageContractTests(unittest.TestCase):
    def test_all_json_files_parse(self) -> None:
        for path in REPO_ROOT.rglob("*.json"):
            with self.subTest(path=path.relative_to(REPO_ROOT)):
                json.loads(path.read_text(encoding="utf-8"))

    def test_manifest_and_marketplace_names_match(self) -> None:
        manifest = json.loads(
            (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text()
        )
        marketplace = json.loads(
            (REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text()
        )
        self.assertEqual(manifest["name"], "outward-copy-quality-gate")
        self.assertEqual(manifest["version"], "0.1.1")
        self.assertEqual(marketplace["plugins"][0]["name"], manifest["name"])
        self.assertNotIn("hooks", manifest)
        self.assertTrue((PLUGIN_ROOT / "hooks" / "hooks.json").is_file())
        long_description = manifest["interface"]["longDescription"]
        self.assertIn("configured outward-facing copy families", long_description)
        self.assertIn("same-turn, hash-bound declaration", long_description)
        self.assertIn("do not prove semantic execution", long_description)

    def test_package_alignment_validator(self) -> None:
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "validate_package.py")],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "pass")

    def test_portability_fixtures_are_synthetic(self) -> None:
        namespace = runpy.run_path(
            str(PLUGIN_ROOT / "scripts" / "validate_package.py")
        )
        fixtures = namespace["FORBIDDEN_PORTABILITY_TEXT"]
        fixture_pattern = namespace["SYNTHETIC_FIXTURE_PATTERN"]
        self.assertGreater(len(fixtures), 0)
        self.assertTrue(
            all(fixture_pattern.fullmatch(value) for value in fixtures),
            "Portability fixtures must use generic synthetic identities only",
        )

    def test_validator_rejects_generated_bytecode_in_public_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied_repo = Path(temporary) / "marketplace"
            shutil.copytree(REPO_ROOT, copied_repo, ignore=shutil.ignore_patterns(".git"))
            bytecode = (
                copied_repo
                / "plugins"
                / "outward-copy-quality-gate"
                / "hooks"
                / "__pycache__"
                / "gate_core.synthetic.pyc"
            )
            bytecode.parent.mkdir(parents=True)
            bytecode.write_bytes(b"synthetic-bytecode-fixture")
            env = os.environ.copy()
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            result = subprocess.run(
                [
                    sys.executable,
                    str(
                        copied_repo
                        / "plugins"
                        / "outward-copy-quality-gate"
                        / "scripts"
                        / "validate_package.py"
                    ),
                    "--repo-root",
                    str(copied_repo),
                ],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            errors = json.loads(result.stdout)["errors"]
            self.assertTrue(
                any(error.startswith("generated_runtime_artifact:") for error in errors),
                errors,
            )


if __name__ == "__main__":
    unittest.main()
