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
COMPATIBILITY_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "latest-codex-compatibility.yml"
)
TEST_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"


class PackageContractTests(unittest.TestCase):
    def test_all_json_files_parse(self) -> None:
        for path in REPO_ROOT.rglob("*.json"):
            with self.subTest(path=path.relative_to(REPO_ROOT)):
                json.loads(path.read_text(encoding="utf-8"))

    def test_manifest_marketplace_policy_and_hooks_match(self) -> None:
        manifest = json.loads(
            (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text()
        )
        marketplace = json.loads(
            (REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text()
        )
        policy = json.loads(
            (PLUGIN_ROOT / "policy" / "outward-copy-policy.json").read_text()
        )
        hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
        self.assertEqual(manifest["name"], "outward-copy-quality-gate")
        self.assertEqual(manifest["version"], "0.2.0")
        self.assertEqual(policy["plugin_version"], manifest["version"])
        self.assertEqual(policy["required_hook_events"], ["UserPromptSubmit"])
        self.assertEqual(set(hooks["hooks"]), {"UserPromptSubmit"})
        self.assertEqual(marketplace["plugins"][0]["name"], manifest["name"])
        self.assertNotIn("hooks", manifest)
        long_description = manifest["interface"]["longDescription"]
        self.assertIn("inject exact", long_description)
        self.assertIn("Errors fail open", long_description)
        self.assertIn("never blocks", long_description)

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

    def test_latest_codex_workflow_proves_the_real_hook_lifecycle(self) -> None:
        workflow = COMPATIBILITY_WORKFLOW.read_text(encoding="utf-8")
        before_steps = workflow.split("    steps:", 1)[0]
        self.assertNotIn("runner.temp", before_steps)
        for required in (
            "schedule:",
            'cron: "17 5 * * *"',
            "@openai/codex@latest",
            "tests/mock_responses_server.py",
            "codex exec --ephemeral",
            "model_providers.route09.requires_openai_auth=false",
            "Rewrite this README title so it is clear and searchable.",
            "Update the README parser implementation and rerun unit tests.",
            "tests/assert_lifecycle_capture.py",
            "--expect active",
            "--expect silent",
            "actions/checkout@v6",
            "actions/setup-node@v6",
            "actions/setup-python@v6",
            "actions/github-script@v9",
            "issues: write",
            "github.paginate",
            "github.rest.issues.create",
            "github.rest.issues.update",
            "Latest Codex compatibility check failed",
            "context.runId",
        ):
            with self.subTest(required=required):
                self.assertIn(required, workflow)
        for forbidden in ("OPENAI_API_KEY", "CODEX_API_KEY", "secrets."):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, workflow)
        for retired_action in (
            "actions/checkout@v4",
            "actions/setup-node@v4",
            "actions/setup-python@v5",
            "actions/github-script@v7",
        ):
            with self.subTest(retired_action=retired_action):
                self.assertNotIn(retired_action, workflow)

    def test_readme_exposes_latest_codex_status(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Latest Codex compatibility", readme)
        self.assertIn("latest-codex-compatibility.yml/badge.svg", readme)

    def test_primary_workflow_uses_current_node24_actions(self) -> None:
        workflow = TEST_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("actions/checkout@v6", workflow)
        self.assertIn("actions/setup-python@v6", workflow)
        self.assertNotIn("actions/checkout@v4", workflow)
        self.assertNotIn("actions/setup-python@v5", workflow)

    def test_portability_fixtures_are_synthetic(self) -> None:
        namespace = runpy.run_path(
            str(PLUGIN_ROOT / "scripts" / "validate_package.py")
        )
        fixtures = namespace["FORBIDDEN_PORTABILITY_TEXT"]
        fixture_pattern = namespace["SYNTHETIC_FIXTURE_PATTERN"]
        self.assertTrue(fixtures)
        self.assertTrue(all(fixture_pattern.fullmatch(value) for value in fixtures))

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

    def test_validator_rejects_reordered_skill_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied_repo = Path(temporary) / "marketplace"
            shutil.copytree(REPO_ROOT, copied_repo, ignore=shutil.ignore_patterns(".git"))
            policy_path = (
                copied_repo
                / "plugins"
                / "outward-copy-quality-gate"
                / "policy"
                / "outward-copy-policy.json"
            )
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["skills"] = list(reversed(policy["skills"]))
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
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
            self.assertIn(
                "policy_skill_order_invalid",
                json.loads(result.stdout)["errors"],
            )


if __name__ == "__main__":
    unittest.main()
