from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "outward-copy-quality-gate"
USER_HOOK = PLUGIN_ROOT / "hooks" / "user_prompt_submit.py"
DISPATCHER = PLUGIN_ROOT / "hooks" / "version_resilient_dispatch.py"
EXACT_PROMPT = (
    "Make the GitHub title more searchable with Windows LLM coding fixes skill WSL terms"
)
EXPECTED_SKILL_ORDER = (
    (
        "outward-copy-quality-gate-router",
        "skills/outward-copy-quality-gate-router/SKILL.md",
    ),
    (
        "outward-copy-quality-gate-humanizer",
        "skills/outward-copy-quality-gate-humanizer/SKILL.md",
    ),
    (
        "outward-copy-quality-gate-ogilvy",
        "skills/outward-copy-quality-gate-ogilvy/SKILL.md",
    ),
)


class HookContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temporary.name)
        self.env = os.environ.copy()
        self.env["PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        self.env["PLUGIN_DATA"] = str(self.temp_root / "plugin-data")
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def prompt_event(prompt: str = EXACT_PROMPT, turn_id: str = "turn-1") -> dict:
        return {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-1",
            "turn_id": turn_id,
            "cwd": str(REPO_ROOT),
            "prompt": prompt,
        }

    def run_script(
        self, script: Path, event: dict, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            env=env or self.env,
            check=False,
        )

    @staticmethod
    def payload(result: subprocess.CompletedProcess[str]) -> dict:
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        return json.loads(result.stdout)

    def assert_nonblocking_payload(self, payload: object) -> None:
        def walk(value: object) -> None:
            if isinstance(value, dict):
                self.assertNotEqual(str(value.get("decision", "")).lower(), "block")
                self.assertIsNot(value.get("continue", True), False)
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(payload)

    def test_exact_old_prompt_injects_ordered_skills_without_state_or_block(self) -> None:
        result = self.run_script(USER_HOOK, self.prompt_event())
        payload = self.payload(result)
        self.assert_nonblocking_payload(payload)
        context = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Continue the current user task", context)
        self.assertIn("No receipt or marker is required", context)
        previous_position = -1
        for skill_id, relative_path in EXPECTED_SKILL_ORDER:
            skill_path = (PLUGIN_ROOT / relative_path).resolve()
            self.assertIn(f"Skill ID: {skill_id}", context)
            position = context.index(f"Resolved SKILL.md path: {skill_path}")
            self.assertGreater(position, previous_position)
            previous_position = position
            self.assertIn(skill_path.read_text(encoding="utf-8").rstrip(), context)
        self.assertNotIn(EXACT_PROMPT, context)
        self.assertFalse(Path(self.env["PLUGIN_DATA"]).exists())

    def test_duplicate_catalog_names_do_not_override_bundled_skills(self) -> None:
        duplicate = (
            self.temp_root
            / "codex-home"
            / "skills"
            / "outward-copy-quality-gate-humanizer"
            / "SKILL.md"
        )
        duplicate.parent.mkdir(parents=True)
        duplicate.write_text(
            "---\nname: outward-copy-quality-gate-humanizer\n"
            "description: Synthetic duplicate catalog fixture.\n---\n"
            "DUPLICATE-CATALOG-SENTINEL\n",
            encoding="utf-8",
        )
        env = dict(self.env)
        env["CODEX_HOME"] = str(self.temp_root / "codex-home")
        context = self.payload(
            self.run_script(USER_HOOK, self.prompt_event(turn_id="duplicate"), env)
        )["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("DUPLICATE-CATALOG-SENTINEL", context)
        self.assertNotIn(str(duplicate.resolve()), context)

    def test_missing_unsafe_and_oversized_skills_degrade_without_blocking(self) -> None:
        for case in ("missing", "unsafe", "oversized"):
            with self.subTest(case=case):
                copied_root = self.temp_root / case / "plugin"
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
                        + "\nSynthetic private path: /home/synthetic-user/project\n",
                        encoding="utf-8",
                    )
                else:
                    skill_path.write_bytes(b"x" * (32 * 1024 + 1))
                env = dict(self.env)
                env["PLUGIN_ROOT"] = str(copied_root)
                result = self.run_script(
                    copied_root / "hooks" / "user_prompt_submit.py",
                    self.prompt_event(turn_id=case),
                    env,
                )
                payload = self.payload(result)
                self.assert_nonblocking_payload(payload)
                context = payload["hookSpecificOutput"]["additionalContext"]
                self.assertIn("ROUTING DEGRADED", context)
                self.assertIn("Continue the current user task; do not stop", context)

    def test_plugin_data_is_irrelevant_and_legacy_state_is_inert(self) -> None:
        legacy = Path(self.env["PLUGIN_DATA"]) / "turn-state" / "pending.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text('{"status":"pending","prompt_sha256":"synthetic"}\n')
        before = legacy.read_bytes()
        result = self.run_script(USER_HOOK, self.prompt_event(turn_id="legacy"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(legacy.read_bytes(), before)
        self.assertEqual(list(legacy.parent.iterdir()), [legacy])

    def test_all_negative_fixtures_are_silent(self) -> None:
        fixtures = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "classifier-negative.json").read_text()
        )
        for fixture in fixtures:
            with self.subTest(fixture["id"]):
                result = self.run_script(
                    USER_HOOK,
                    self.prompt_event(
                        prompt=fixture["prompt"], turn_id=fixture["id"]
                    ),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_all_positive_fixtures_route_all_three_skills(self) -> None:
        fixtures = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "classifier-positive.json").read_text()
        )
        for fixture in fixtures:
            with self.subTest(fixture["id"]):
                payload = self.payload(
                    self.run_script(
                        USER_HOOK,
                        self.prompt_event(
                            prompt=fixture["prompt"], turn_id=fixture["id"]
                        ),
                    )
                )
                self.assert_nonblocking_payload(payload)
                context = payload["hookSpecificOutput"]["additionalContext"]
                self.assertIn(
                    f"Matched scopes: {', '.join(fixture['scopes'])}.",
                    context,
                )
                for skill_id, _ in EXPECTED_SKILL_ORDER:
                    self.assertIn(f"Skill ID: {skill_id}", context)

    def test_reordered_runtime_policy_degrades_instead_of_silently_reordering(self) -> None:
        copied_root = self.temp_root / "reordered-policy"
        shutil.copytree(PLUGIN_ROOT, copied_root)
        policy_path = copied_root / "policy" / "outward-copy-policy.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["skills"] = list(reversed(policy["skills"]))
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        env = dict(self.env)
        env["PLUGIN_ROOT"] = str(copied_root)
        payload = self.payload(
            self.run_script(
                copied_root / "hooks" / "user_prompt_submit.py",
                self.prompt_event(turn_id="reordered-policy"),
                env,
            )
        )
        self.assert_nonblocking_payload(payload)
        self.assertIn(
            "ROUTING DEGRADED",
            payload["hookSpecificOutput"]["additionalContext"],
        )

    def test_invalid_input_warns_without_block_and_unrelated_prompt_is_silent(self) -> None:
        invalid = subprocess.run(
            [sys.executable, str(USER_HOOK)],
            input="not-json",
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(invalid.returncode, 0, invalid.stderr)
        invalid_payload = self.payload(invalid)
        self.assert_nonblocking_payload(invalid_payload)
        self.assertIn(
            "ROUTING DEGRADED",
            invalid_payload["hookSpecificOutput"]["additionalContext"],
        )
        unrelated = self.run_script(
            USER_HOOK,
            self.prompt_event(prompt="Explain this Linux shell command."),
        )
        self.assertEqual(unrelated.returncode, 0, unrelated.stderr)
        self.assertEqual(unrelated.stdout, "")
        self.assertFalse(Path(self.env["PLUGIN_DATA"]).exists())

    def test_compatibility_alias_for_prompt_field_still_routes(self) -> None:
        event = self.prompt_event()
        event["user_prompt"] = event.pop("prompt")
        payload = self.payload(self.run_script(USER_HOOK, event))
        self.assert_nonblocking_payload(payload)
        self.assertIn(
            "OUTWARD COPY ROUTE ACTIVE",
            payload["hookSpecificOutput"]["additionalContext"],
        )

    def test_dispatcher_sanitizes_a_regressed_blocking_child(self) -> None:
        copied_root = self.temp_root / "blocking-child"
        shutil.copytree(PLUGIN_ROOT, copied_root)
        (copied_root / "hooks" / "user_prompt_submit.py").write_text(
            "import json\nprint(json.dumps({'decision':'block','reason':'synthetic'}))\n",
            encoding="utf-8",
        )
        env = dict(self.env)
        env["PLUGIN_ROOT"] = str(copied_root)
        payload = self.payload(
            self.run_script(
                copied_root / "hooks" / "version_resilient_dispatch.py",
                self.prompt_event(),
                env,
            )
        )
        self.assert_nonblocking_payload(payload)
        self.assertIn(
            "ROUTING DEGRADED",
            payload["hookSpecificOutput"]["additionalContext"],
        )

    def test_dispatcher_invalid_or_oversized_event_warns_without_block(self) -> None:
        env = dict(self.env)
        for event in (b"", b"x" * (2 * 1024 * 1024 + 1)):
            with self.subTest(size=len(event)):
                result = subprocess.run(
                    [sys.executable, str(DISPATCHER)],
                    input=event,
                    capture_output=True,
                    env=env,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                payload = json.loads(result.stdout)
                self.assert_nonblocking_payload(payload)
                self.assertIn(
                    "ROUTING DEGRADED",
                    payload["hookSpecificOutput"]["additionalContext"],
                )

    def test_dispatcher_marks_an_intentional_classifier_miss(self) -> None:
        result = self.run_script(
            DISPATCHER,
            self.prompt_event(prompt="Explain this Linux shell command."),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "outwardCopyRouting": {
                    "protocol": 1,
                    "result": "not_applicable",
                }
            },
        )

    def run_loaded_command(
        self, command: str, plugin_root: Path, prompt: str = EXACT_PROMPT
    ) -> subprocess.CompletedProcess[str]:
        env = dict(self.env)
        env["PLUGIN_ROOT"] = str(plugin_root)
        return subprocess.run(
            command,
            shell=True,
            executable="/bin/sh",
            input=json.dumps(self.prompt_event(prompt=prompt)),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def test_loaded_command_survives_deleted_original_version(self) -> None:
        command = json.loads(
            (PLUGIN_ROOT / "hooks" / "hooks.json").read_text()
        )["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        versions = self.temp_root / "cache" / "market" / "plugin"
        old_root = versions / "0.2.0"
        new_root = versions / "0.2.1+codex.local-synthetic"
        shutil.copytree(PLUGIN_ROOT, old_root)
        shutil.copytree(PLUGIN_ROOT, new_root)
        shutil.rmtree(old_root)
        result = self.run_loaded_command(command, old_root)
        payload = self.payload(result)
        self.assert_nonblocking_payload(payload)
        context = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn(str(new_root.resolve()), context)
        self.assertNotIn(str(old_root.resolve()), context)

        unrelated = self.run_loaded_command(
            command,
            old_root,
            "Update the README parser implementation and rerun unit tests.",
        )
        self.assertEqual(unrelated.returncode, 0, unrelated.stderr)
        self.assertEqual(unrelated.stdout, "")

    def test_loaded_command_keeps_every_engineering_fixture_silent(self) -> None:
        command = json.loads(
            (PLUGIN_ROOT / "hooks" / "hooks.json").read_text()
        )["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        fixtures = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "classifier-negative.json").read_text()
        )
        for fixture in fixtures:
            with self.subTest(fixture["id"]):
                result = self.run_loaded_command(
                    command,
                    PLUGIN_ROOT,
                    fixture["prompt"],
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_loaded_command_sanitizes_malicious_newest_dispatcher(self) -> None:
        command = json.loads(
            (PLUGIN_ROOT / "hooks" / "hooks.json").read_text()
        )["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        for malicious in (
            "{'decision':'block','reason':'synthetic'}",
            "{'hookSpecificOutput':{'continue':False}}",
        ):
            with self.subTest(malicious=malicious):
                versions = self.temp_root / ("malicious-" + str(abs(hash(malicious))))
                old_root = versions / "0.2.0"
                newest = versions / "0.2.1"
                shutil.copytree(PLUGIN_ROOT, old_root)
                shutil.copytree(PLUGIN_ROOT, newest)
                (newest / "hooks" / "version_resilient_dispatch.py").write_text(
                    f"import json\nprint(json.dumps({malicious}))\n",
                    encoding="utf-8",
                )
                result = self.run_loaded_command(command, old_root)
                payload = self.payload(result)
                self.assert_nonblocking_payload(payload)
                self.assertIn(
                    "ROUTING DEGRADED",
                    payload["hookSpecificOutput"]["additionalContext"],
                )

    def test_loaded_command_rejects_empty_or_wrong_shape_from_newest_dispatcher(self) -> None:
        command = json.loads(
            (PLUGIN_ROOT / "hooks" / "hooks.json").read_text()
        )["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        cases = {
            "empty": "",
            "wrong-shape": (
                "import json\n"
                "print(json.dumps({'unrelated':'shape'}))\n"
            ),
        }
        for case, source in cases.items():
            with self.subTest(case=case):
                versions = self.temp_root / f"malformed-{case}"
                old_root = versions / "0.2.0"
                newest = versions / "0.2.2"
                shutil.copytree(PLUGIN_ROOT, old_root)
                shutil.copytree(PLUGIN_ROOT, newest)
                (newest / "hooks" / "version_resilient_dispatch.py").write_text(
                    source,
                    encoding="utf-8",
                )
                result = self.run_loaded_command(command, old_root)
                payload = self.payload(result)
                self.assert_nonblocking_payload(payload)
                self.assertIn(
                    "ROUTING DEGRADED",
                    payload["hookSpecificOutput"]["additionalContext"],
                )

    def test_loaded_command_times_out_hanging_newest_dispatcher_before_hook_limit(self) -> None:
        command = json.loads(
            (PLUGIN_ROOT / "hooks" / "hooks.json").read_text()
        )["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        versions = self.temp_root / "hanging"
        old_root = versions / "0.2.0"
        newest = versions / "0.2.1"
        shutil.copytree(PLUGIN_ROOT, old_root)
        shutil.copytree(PLUGIN_ROOT, newest)
        (newest / "hooks" / "version_resilient_dispatch.py").write_text(
            "import time\ntime.sleep(30)\n",
            encoding="utf-8",
        )
        started = time.monotonic()
        result = self.run_loaded_command(command, old_root)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 9, result.stderr)
        payload = self.payload(result)
        self.assert_nonblocking_payload(payload)
        self.assertIn(
            "ROUTING UNAVAILABLE",
            payload["hookSpecificOutput"]["additionalContext"],
        )

    def test_loaded_command_without_any_version_fails_open_with_instructions(self) -> None:
        command = json.loads(
            (PLUGIN_ROOT / "hooks" / "hooks.json").read_text()
        )["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        missing_root = self.temp_root / "empty-cache" / "plugin" / "0.1.0"
        missing_root.parent.mkdir(parents=True)
        result = self.run_loaded_command(command, missing_root)
        payload = self.payload(result)
        self.assert_nonblocking_payload(payload)
        context = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Continue the current user task; do not stop", context)
        self.assertIn("plugin update or reinstall", context)

    def test_hook_map_has_no_stop_and_active_child_has_no_block_contract(self) -> None:
        hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
        self.assertEqual(set(hooks["hooks"]), {"UserPromptSubmit"})
        self.assertFalse((PLUGIN_ROOT / "hooks" / "stop_guard.py").exists())
        source = USER_HOOK.read_text(encoding="utf-8")
        self.assertNotIn('"decision"', source)
        self.assertNotIn("return 2", source)
        self.assertNotIn("PLUGIN_DATA", source)

    def test_posix_and_windows_launchers_run_the_same_python_program(self) -> None:
        handler = json.loads(
            (PLUGIN_ROOT / "hooks" / "hooks.json").read_text()
        )["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        self.assertEqual(
            handler["command"].split(' -c "', 1)[1].split('"', 1)[0],
            handler["commandWindows"].split(' -c "', 1)[1].split('"', 1)[0],
        )
        self.assertIn("|| printf", handler["command"])
        self.assertIn("|| echo", handler["commandWindows"])

    def test_missing_python_runtime_still_exits_zero_with_recovery_guidance(self) -> None:
        command = json.loads(
            (PLUGIN_ROOT / "hooks" / "hooks.json").read_text()
        )["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        command = command.replace("python3 -c", "python3-that-does-not-exist -c", 1)
        result = self.run_loaded_command(command, PLUGIN_ROOT)
        payload = self.payload(result)
        self.assert_nonblocking_payload(payload)
        context = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn("ROUTING UNAVAILABLE", context)
        self.assertIn("Check Python 3", context)


if __name__ == "__main__":
    unittest.main()
