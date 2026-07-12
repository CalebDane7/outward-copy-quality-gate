#!/usr/bin/env python3
"""Stop hook: validate one same-turn receipt and request at most one repair."""

from __future__ import annotations

import json

from gate_core import (
    GateError,
    atomic_write_json,
    build_receipt,
    load_policy,
    parse_marker,
    read_private_json,
    read_stdin_event,
    receipt_path,
    require_plugin_data,
    require_plugin_root,
    safe_repair_reason,
    skill_records,
    state_path,
    turn_key,
    validate_marker,
    validate_receipt_shape,
)


def emit(value: dict) -> None:
    print(json.dumps(value, separators=(",", ":")))


def main() -> int:
    event: dict = {}
    try:
        event = read_stdin_event()
        stop_hook_active = bool(event.get("stop_hook_active"))
        plugin_root = require_plugin_root()
        plugin_data = require_plugin_data()
        session_id = str(event.get("session_id") or "")
        turn_id = str(event.get("turn_id") or "")
        if not session_id or not turn_id:
            raise GateError("turn_identity_missing")

        key = turn_key(session_id, turn_id)
        pending_path = state_path(plugin_data, key)
        if not pending_path.is_file():
            emit({})
            return 0

        state = read_private_json(pending_path)
        message = event.get("last_assistant_message")
        if not isinstance(message, str):
            raise GateError("assistant_message_missing")
        policy, policy_sha256 = load_policy(plugin_root)
        current_skills = skill_records(plugin_root, policy)
        marker, match = parse_marker(message)
        validate_marker(marker, state, policy_sha256, current_skills)
        receipt = build_receipt(state=state, marker=marker, message=message, match=match)
        errors = validate_receipt_shape(receipt, policy, current_skills)
        if errors:
            raise GateError(errors[0])
        atomic_write_json(receipt_path(plugin_data, key), receipt)
        state["status"] = "validated"
        state["validated_at"] = receipt["validated_at"]
        atomic_write_json(pending_path, state)
        emit({})
        return 0
    except GateError as exc:
        # WHY: Stop continuation creates another Stop event. Validate a repaired
        # marker on that event, but never request a second continuation loop.
        if bool(event.get("stop_hook_active")):
            emit({})
            return 0
        emit({"decision": "block", "reason": safe_repair_reason(exc.code)})
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
