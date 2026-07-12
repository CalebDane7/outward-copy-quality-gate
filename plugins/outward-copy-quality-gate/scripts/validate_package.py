#!/usr/bin/env python3
"""Check marketplace, plugin, hook, policy, skill, and receipt alignment."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# WHY: validation must not create the bytecode artifact it is responsible for
# rejecting from the publishable plugin subtree.
sys.dont_write_bytecode = True


PLUGIN_NAME = "outward-copy-quality-gate"
FORBIDDEN_RUNTIME_DIRECTORIES = {
    "__pycache__",
    ".ai-controller",
    ".tldr",
}
FORBIDDEN_RUNTIME_FILES = {
    ".tldrignore",
}
FORBIDDEN_BYTECODE_SUFFIXES = {
    ".pyc",
    ".pyo",
}
EXPECTED_SKILLS = {
    "outward-copy-quality-gate-router",
    "outward-copy-quality-gate-humanizer",
    "outward-copy-quality-gate-ogilvy",
}
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

    # WHY: Codex installs by copying the complete plugin subtree, so ignored
    # generated files are still publication inputs unless validation rejects them.
    for path in plugin_root.rglob("*"):
        is_runtime_directory = (
            path.is_dir() and path.name in FORBIDDEN_RUNTIME_DIRECTORIES
        )
        is_runtime_file = path.is_file() and (
            path.name in FORBIDDEN_RUNTIME_FILES
            or path.suffix.lower() in FORBIDDEN_BYTECODE_SUFFIXES
        )
        if is_runtime_directory or is_runtime_file:
            errors.append(
                f"generated_runtime_artifact:{path.relative_to(repo_root)}"
            )

    # WHY: Portability guards must exercise detection without preserving a real
    # operator path, profile, or account label in a publishable package.
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
            if not entry.get("category"):
                errors.append("marketplace_category_missing")

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
    if set(hook_map) != {"UserPromptSubmit", "Stop"}:
        errors.append("hook_events_invalid")
    for event, script in (
        ("UserPromptSubmit", "user_prompt_submit.py"),
        ("Stop", "stop_guard.py"),
    ):
        try:
            handler = hook_map[event][0]["hooks"][0]
        except (KeyError, IndexError, TypeError):
            errors.append(f"{event}_handler_invalid")
            continue
        if handler.get("type") != "command":
            errors.append(f"{event}_handler_type_invalid")
        command = str(handler.get("command", ""))
        command_windows = str(handler.get("commandWindows", ""))
        if "$PLUGIN_ROOT" not in command or script not in command:
            errors.append(f"{event}_plugin_root_missing")
        if "%PLUGIN_ROOT%" not in command_windows or script not in command_windows:
            errors.append(f"{event}_windows_plugin_root_missing")

    policy = load_json(
        plugin_root / "policy" / "outward-copy-policy.json", errors, "policy"
    )
    if policy.get("plugin_version") != manifest.get("version"):
        errors.append("manifest_policy_version_mismatch")
    if set(policy.get("required_hook_events", [])) != {"UserPromptSubmit", "Stop"}:
        errors.append("policy_hook_events_invalid")
    if set(policy.get("required_scopes", [])) != EXPECTED_SCOPES:
        errors.append("policy_scopes_invalid")
    policy_skills = policy.get("skills", [])
    if not isinstance(policy_skills, list):
        policy_skills = []
    policy_skill_ids = {entry.get("id") for entry in policy_skills if isinstance(entry, dict)}
    if policy_skill_ids != EXPECTED_SKILLS:
        errors.append("policy_skills_invalid")
    long_description = str(manifest.get("interface", {}).get("longDescription", ""))
    if (
        "configured outward-facing copy families" not in long_description
        or "same-turn, hash-bound declaration" not in long_description
        or "do not prove semantic execution" not in long_description
    ):
        errors.append("manifest_enforcement_claim_inaccurate")

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
        openai_yaml = skill_dir / "agents" / "openai.yaml"
        if not openai_yaml.is_file():
            errors.append(f"skill_ui_metadata_missing:{skill_dir.name}")
    if set(discovered_names) != EXPECTED_SKILLS or len(discovered_names) != len(
        set(discovered_names)
    ):
        errors.append("bundled_skill_names_invalid_or_ambiguous")
    combined_descriptions = " ".join(descriptions)
    for term in DESCRIPTION_TERMS:
        if term not in combined_descriptions:
            errors.append(f"skill_metadata_missing_term:{term}")

    schema = load_json(
        plugin_root / "schemas" / "receipt.schema.json", errors, "receipt_schema"
    )
    sys.path.insert(0, str(plugin_root / "hooks"))
    try:
        from gate_core import RECEIPT_REQUIRED_FIELDS, SCOPE_ORDER

        if set(schema.get("required", [])) != RECEIPT_REQUIRED_FIELDS:
            errors.append("receipt_schema_required_fields_invalid")
        if set(SCOPE_ORDER) != EXPECTED_SCOPES:
            errors.append("classifier_policy_scope_drift")
    except Exception:
        errors.append("gate_core_import_failed")

    python_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((plugin_root / "hooks").glob("*.py"))
    )
    if "PLUGIN_ROOT" not in python_text or "PLUGIN_DATA" not in python_text:
        errors.append("plugin_environment_contract_missing")

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
