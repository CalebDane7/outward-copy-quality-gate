#!/usr/bin/env python3
"""UserPromptSubmit hook: inject copy skills without blocking the user turn."""

from __future__ import annotations

import json

from gate_core import (
    GateError,
    additional_context,
    classify_prompt,
    degraded_context,
    load_policy,
    load_skill_materials,
    read_stdin_event,
    require_plugin_root,
)


def emit_context(context: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            },
            separators=(",", ":"),
        )
    )


def main() -> int:
    try:
        event = read_stdin_event()
    except GateError:
        # WHY: if a Codex update changes the event schema, silence would look
        # healthy while routing had stopped. Warn the model and keep work moving.
        emit_context(degraded_context())
        return 0
    prompt = event.get("prompt", event.get("user_prompt"))
    if not isinstance(prompt, str):
        emit_context(degraded_context())
        return 0
    scopes = classify_prompt(prompt)
    if not scopes:
        return 0

    try:
        plugin_root = require_plugin_root()
        policy, _ = load_policy(plugin_root)
        materials = load_skill_materials(plugin_root, policy)
        emit_context(additional_context(scopes, materials))
    except GateError:
        # WHY: stale cache or bundled-skill faults used to reject the prompt and
        # strand important sessions. Give Codex a safe recovery path and continue.
        emit_context(degraded_context())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
