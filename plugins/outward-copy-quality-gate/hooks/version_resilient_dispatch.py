#!/usr/bin/env python3
"""Fail-open wrapper for a UserPromptSubmit implementation in this plugin version."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


MAX_EVENT_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024
DEGRADED_CONTEXT = (
    "OUTWARD COPY ROUTING DEGRADED. Continue the current user task; do not stop. "
    "If this is outward-facing copy, apply the installed outward-copy router, "
    "Humanizer, and Ogilvy skills before finalizing. Repair this plugin with the "
    "supported Codex plugin update or reinstall flow after the current task."
)


def emit_degraded() -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": DEGRADED_CONTEXT,
                }
            },
            separators=(",", ":"),
        )
    )


def emit_not_applicable() -> None:
    # WHY: an explicit private protocol result lets the stable outer launcher
    # distinguish an intentional classifier miss from a broken no-output update.
    # The outer launcher consumes this object; Codex still receives no hook output.
    print(
        json.dumps(
            {
                "outwardCopyRouting": {
                    "protocol": 1,
                    "result": "not_applicable",
                }
            },
            separators=(",", ":"),
        )
    )


def contains_blocking_field(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "decision" and str(item).lower() == "block":
                return True
            if key == "continue" and item is False:
                return True
            if contains_blocking_field(item):
                return True
    elif isinstance(value, list):
        return any(contains_blocking_field(item) for item in value)
    return False


def valid_hook_payload(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"hookSpecificOutput"}:
        return False
    specific = value.get("hookSpecificOutput")
    return (
        isinstance(specific, dict)
        and set(specific) == {"hookEventName", "additionalContext"}
        and specific.get("hookEventName") == "UserPromptSubmit"
        and isinstance(specific.get("additionalContext"), str)
        and bool(specific["additionalContext"].strip())
    )


def main() -> int:
    try:
        event = sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
        if not event or len(event) > MAX_EVENT_BYTES:
            emit_degraded()
            return 0
        plugin_root = Path(os.environ.get("PLUGIN_ROOT", "")).resolve()
        target = plugin_root / "hooks" / "user_prompt_submit.py"
        if not target.is_file() or target.resolve() == Path(__file__).resolve():
            emit_degraded()
            return 0
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, str(target)],
            input=event,
            capture_output=True,
            env=env,
            timeout=3,
            check=False,
        )
        if result.returncode != 0 or len(result.stdout) > MAX_OUTPUT_BYTES:
            emit_degraded()
            return 0
        if not result.stdout:
            emit_not_applicable()
            return 0
        try:
            payload = json.loads(result.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError):
            emit_degraded()
            return 0
        # WHY: the wrapper is the last safety boundary. Even a regressed child
        # hook is converted into actionable guidance instead of a blocked turn.
        if not valid_hook_payload(payload) or contains_blocking_field(payload):
            emit_degraded()
            return 0
        print(json.dumps(payload, separators=(",", ":")))
    except Exception:
        emit_degraded()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
