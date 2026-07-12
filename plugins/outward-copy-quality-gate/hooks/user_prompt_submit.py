#!/usr/bin/env python3
"""UserPromptSubmit hook: classify and open a hash-only copy transaction."""

from __future__ import annotations

import json

from gate_core import (
    GateError,
    additional_context,
    atomic_write_json,
    classify_prompt,
    load_skill_materials,
    load_policy,
    new_turn_state,
    read_stdin_event,
    records_from_materials,
    require_plugin_data,
    require_plugin_root,
    state_path,
)


def block(reason: str) -> None:
    print(json.dumps({"decision": "block", "reason": reason}, separators=(",", ":")))


def main() -> int:
    try:
        event = read_stdin_event()
        prompt = event.get("prompt")
        if not isinstance(prompt, str):
            raise GateError("invalid_hook_input")
        scopes = classify_prompt(prompt)
        if not scopes:
            return 0

        plugin_root = require_plugin_root()
        plugin_data = require_plugin_data()
        policy, policy_sha256 = load_policy(plugin_root)
        materials = load_skill_materials(plugin_root, policy)
        state = new_turn_state(
            policy=policy,
            policy_sha256=policy_sha256,
            session_id=str(event.get("session_id") or ""),
            turn_id=str(event.get("turn_id") or ""),
            prompt=prompt,
            scopes=scopes,
            skills=records_from_materials(materials),
        )
        context = additional_context(state, materials)
        atomic_write_json(state_path(plugin_data, state["turn_key"]), state)
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
        return 0
    except GateError:
        # WHY: a positive copy classification without durable turn state cannot
        # be repaired at Stop. Block generically without echoing the prompt.
        block(
            "Outward Copy Quality Gate could not create privacy-safe turn state. "
            "Check that this plugin's hooks are enabled and trusted, and that "
            "PLUGIN_ROOT and PLUGIN_DATA are available."
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
