#!/usr/bin/env python3
"""Validate an exported receipt without printing prompt or copy content."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--message-file", type=Path)
    parser.add_argument("--plugin-root", type=Path)
    args = parser.parse_args()

    plugin_root = (
        args.plugin_root.resolve()
        if args.plugin_root
        else Path(__file__).resolve().parents[1]
    )
    sys.path.insert(0, str(plugin_root / "hooks"))
    from gate_core import (  # pylint: disable=import-error,import-outside-toplevel
        load_policy,
        message_without_marker,
        parse_marker,
        sha256_file,
        sha256_text,
        skill_records,
        validate_receipt_shape,
    )

    errors: list[str] = []
    try:
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        receipt = {}
        errors.append("receipt_unreadable")
    if not isinstance(receipt, dict):
        receipt = {}
        errors.append("receipt_invalid_shape")

    try:
        policy, policy_sha256 = load_policy(plugin_root)
        skills = skill_records(plugin_root, policy)
        errors.extend(validate_receipt_shape(receipt, policy, skills))
        if receipt.get("policy_sha256") != policy_sha256:
            errors.append("policy_sha256_mismatch")
        if args.message_file:
            message = args.message_file.read_text(encoding="utf-8")
            try:
                _, match = parse_marker(message)
                text = message_without_marker(message, match)
            except Exception:  # The file may contain only the visible copy.
                text = message.rstrip()
            if receipt.get("output_sha256") != sha256_text(text):
                errors.append("output_sha256_mismatch")
        schema_path = plugin_root / "schemas" / "receipt.schema.json"
        if not schema_path.is_file() or not sha256_file(schema_path):
            errors.append("receipt_schema_missing")
    except Exception:
        errors.append("plugin_contract_unavailable")

    errors = sorted(set(errors))
    print(
        json.dumps(
            {"status": "pass" if not errors else "fail", "errors": errors},
            sort_keys=True,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
