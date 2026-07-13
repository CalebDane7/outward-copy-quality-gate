#!/usr/bin/env python3
"""Check marketplace, plugin, nonblocking hook, policy, and skill alignment."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


sys.dont_write_bytecode = True

PLUGIN_NAME = "outward-copy-quality-gate"
FORBIDDEN_RUNTIME_DIRECTORIES = {"__pycache__", ".ai-controller", ".tldr"}
FORBIDDEN_RUNTIME_FILES = {".tldrignore"}
FORBIDDEN_BYTECODE_SUFFIXES = {".pyc", ".pyo"}
EXPECTED_SKILL_ORDER = (
    "outward-copy-quality-gate-router",
    "outward-copy-quality-gate-humanizer",
    "outward-copy-quality-gate-ogilvy",
)
EXPECTED_SKILLS = set(EXPECTED_SKILL_ORDER)
EXPECTED_SCOPES = {
    "title_headline",
    "readme",
    "seo_search",
    "public_docs",
    "repository_metadata",
    "marketing_sales",
    "product_ui_help",
    "general_outward_copy",
}
DESCRIPTION_TERMS = {
    "title",
    "headline",
    "readme",
    "seo",
    "search",
    "public",
    "repository",
}
FORBIDDEN_PORTABILITY_TEXT = (
    "/home/" + "__synthetic_user_fixture__",
    "C:\\Users\\" + "__synthetic_user_fixture__",
    "__synthetic_" + "account_fixture__",
)
SYNTHETIC_FIXTURE_PATTERN = re.compile(
    r"^(?:(?:/home/)|(?:C:\\Users\\))?"
    r"__synthetic_(?:user|account)_fixture__$"
)


def load_json(path: Path, errors: list[str], label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        errors.append(f"{label}_invalid_json")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label}_invalid_shape")
        return {}
    return value


def frontmatter_name_and_description(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return "", ""
    name = ""
    description = ""
    for line in match.group(1).splitlines():
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip()
        if line.startswith("description:"):
            description = line.split(":", 1)[1].strip()
    return name, description


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    args = parser.parse_args()
    repo_root = (
        args.repo_root.resolve()
        if args.repo_root
        else Path(__file__).resolve().parents[3]
    )
    plugin_root = repo_root / "plugins" / PLUGIN_NAME
    errors: list[str] = []

    # WHY: Codex copies the complete plugin subtree, so ignored runtime files
    # are publication inputs unless the package check rejects them.
    for path in plugin_root.rglob("*"):
        runtime_directory = path.is_dir() and path.name in FORBIDDEN_RUNTIME_DIRECTORIES
        runtime_file = path.is_file() and (
            path.name in FORBIDDEN_RUNTIME_FILES
            or path.suffix.lower() in FORBIDDEN_BYTECODE_SUFFIXES
        )
        if runtime_directory or runtime_file:
            errors.append(f"generated_runtime_artifact:{path.relative_to(repo_root)}")

    if not all(
        SYNTHETIC_FIXTURE_PATTERN.fullmatch(value)
        for value in FORBIDDEN_PORTABILITY_TEXT
    ):
        errors.append("portability_fixture_not_synthetic")

    marketplace = load_json(
        repo_root / ".agents" / "plugins" / "marketplace.json",
        errors,
        "marketplace",
    )
    entries = marketplace.get("plugins")
    if marketplace.get("name") != PLUGIN_NAME or not isinstance(entries, list):
        errors.append("marketplace_contract_invalid")
    else:
        matches = [entry for entry in entries if entry.get("name") == PLUGIN_NAME]
        if len(matches) != 1:
            errors.append("marketplace_plugin_entry_invalid")
        else:
            entry = matches[0]
            if entry.get("source") != {
                "source": "local",
                "path": f"./plugins/{PLUGIN_NAME}",
            }:
                errors.append("marketplace_source_invalid")
            if entry.get("policy") != {
                "installation": "AVAILABLE",
                "authentication": "ON_INSTALL",
            }:
                errors.append("marketplace_policy_invalid")

    manifest = load_json(
        plugin_root / ".codex-plugin" / "plugin.json", errors, "plugin_manifest"
    )
    if manifest.get("name") != PLUGIN_NAME:
        errors.append("plugin_name_invalid")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("version", ""))):
        errors.append("plugin_version_invalid")
    if manifest.get("skills") != "./skills/":
        errors.append("plugin_skills_path_invalid")
    if "hooks" in manifest:
        errors.append("manifest_hooks_must_use_default_discovery")
    for field in ("description", "author", "license", "interface"):
        if not manifest.get(field):
            errors.append(f"plugin_{field}_missing")

    hooks = load_json(plugin_root / "hooks" / "hooks.json", errors, "hooks")
    hook_map = hooks.get("hooks") if isinstance(hooks.get("hooks"), dict) else {}
    # WHY: a Stop hook caused the original completion loop. This contract makes
    # re-registering any completion-time hook a publish-time failure.
    if set(hook_map) != {"UserPromptSubmit"}:
        errors.append("hook_events_must_be_user_prompt_submit_only")
    try:
        handler = hook_map["UserPromptSubmit"][0]["hooks"][0]
    except (KeyError, IndexError, TypeError):
        handler = {}
        errors.append("UserPromptSubmit_handler_invalid")
    if handler.get("type") != "command":
        errors.append("UserPromptSubmit_handler_type_invalid")
    command = str(handler.get("command", ""))
    command_windows = str(handler.get("commandWindows", ""))
    for label, value, prefix in (
        ("posix", command, "python3 -c"),
        ("windows", command_windows, "py -3 -c"),
    ):
        if not value.startswith(prefix):
            errors.append(f"{label}_inline_launcher_missing")
        for required in (
            "PLUGIN_ROOT",
            "original.parent",
            "version_resilient_dispatch.py",
            "returncode==0",
            "timeout=5",
            "normalized=",
            "blocked=",
            "not_applicable=",
            "outwardCopyRouting",
            "set(specific)",
            "[-+]",
            "Continue the current user task; do not stop",
            "ROUTING UNAVAILABLE",
        ):
            if required not in value:
                errors.append(f"{label}_launcher_contract_missing:{required}")
        if "stop_guard.py" in value or "decision':'block" in value:
            errors.append(f"{label}_launcher_can_block")
    if "|| printf" not in command or "|| echo" not in command_windows:
        errors.append("outer_runtime_fail_open_missing")

    if (plugin_root / "hooks" / "stop_guard.py").exists():
        errors.append("stop_handler_must_not_ship")
    for required_hook_file in (
        "user_prompt_submit.py",
        "version_resilient_dispatch.py",
        "gate_core.py",
    ):
        if not (plugin_root / "hooks" / required_hook_file).is_file():
            errors.append(f"required_hook_file_missing:{required_hook_file}")

    user_hook_text = (plugin_root / "hooks" / "user_prompt_submit.py").read_text(
        encoding="utf-8"
    )
    if '"decision"' in user_hook_text or "return 2" in user_hook_text:
        errors.append("user_prompt_hook_contains_blocking_contract")
    if "PLUGIN_DATA" in user_hook_text:
        errors.append("user_prompt_hook_must_not_use_plugin_data")
    dispatcher_text = (
        plugin_root / "hooks" / "version_resilient_dispatch.py"
    ).read_text(encoding="utf-8")
    for required in (
        "emit_not_applicable",
        '"protocol": 1',
        '"result": "not_applicable"',
        "valid_hook_payload",
    ):
        if required not in dispatcher_text:
            errors.append(f"dispatcher_protocol_missing:{required}")

    policy = load_json(
        plugin_root / "policy" / "outward-copy-policy.json", errors, "policy"
    )
    if policy.get("plugin_version") != manifest.get("version"):
        errors.append("manifest_policy_version_mismatch")
    if policy.get("required_hook_events") != ["UserPromptSubmit"]:
        errors.append("policy_hook_events_invalid")
    if policy.get("routing_mode") != "nonblocking_additional_context":
        errors.append("policy_routing_mode_invalid")
    if policy.get("failure_mode") != "fail_open_with_actionable_guidance":
        errors.append("policy_failure_mode_invalid")
    if set(policy.get("required_scopes", [])) != EXPECTED_SCOPES:
        errors.append("policy_scopes_invalid")
    policy_skills = policy.get("skills", [])
    if not isinstance(policy_skills, list):
        policy_skills = []
    policy_skill_ids = [
        entry.get("id") for entry in policy_skills if isinstance(entry, dict)
    ]
    if policy_skill_ids != list(EXPECTED_SKILL_ORDER):
        errors.append("policy_skill_order_invalid")
    if policy.get("privacy", {}).get("persist") != []:
        errors.append("runtime_persistence_must_be_empty")

    long_description = str(manifest.get("interface", {}).get("longDescription", ""))
    for truth in ("inject exact", "Errors fail open", "never blocks"):
        if truth not in long_description:
            errors.append(f"manifest_nonblocking_claim_missing:{truth}")

    discovered_names: list[str] = []
    descriptions: list[str] = []
    for skill_dir in sorted((plugin_root / "skills").glob("*")):
        skill_path = skill_dir / "SKILL.md"
        if not skill_path.is_file():
            continue
        name, description = frontmatter_name_and_description(skill_path)
        discovered_names.append(name)
        descriptions.append(description.lower())
        if name != skill_dir.name:
            errors.append(f"skill_folder_name_mismatch:{skill_dir.name}")
        if not (skill_dir / "agents" / "openai.yaml").is_file():
            errors.append(f"skill_ui_metadata_missing:{skill_dir.name}")
    if set(discovered_names) != EXPECTED_SKILLS or len(discovered_names) != len(
        set(discovered_names)
    ):
        errors.append("bundled_skill_names_invalid_or_ambiguous")
    combined_descriptions = " ".join(descriptions)
    for term in DESCRIPTION_TERMS:
        if term not in combined_descriptions:
            errors.append(f"skill_metadata_missing_term:{term}")

    sys.path.insert(0, str(plugin_root / "hooks"))
    try:
        from gate_core import SCOPE_ORDER

        if set(SCOPE_ORDER) != EXPECTED_SCOPES:
            errors.append("classifier_policy_scope_drift")
    except Exception:
        errors.append("gate_core_import_failed")

    for path in repo_root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for forbidden in FORBIDDEN_PORTABILITY_TEXT:
            if forbidden in text:
                errors.append(f"machine_specific_text:{path.relative_to(repo_root)}")

    errors = sorted(set(errors))
    print(
        json.dumps(
            {
                "status": "pass" if not errors else "fail",
                "errors": errors,
                "plugin": PLUGIN_NAME,
            },
            sort_keys=True,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
