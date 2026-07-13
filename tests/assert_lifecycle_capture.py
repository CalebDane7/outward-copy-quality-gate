#!/usr/bin/env python3
"""Assert model-visible routing from a real Codex lifecycle capture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROUTE_MARKERS = (
    "OUTWARD COPY ROUTE ACTIVE.",
    "BEGIN BUNDLED SKILL",
    "OUTWARD COPY ROUTING DEGRADED",
    "OUTWARD COPY ROUTING UNAVAILABLE",
)
EXPECTED_SKILL_ORDER = (
    "Skill ID: outward-copy-quality-gate-router",
    "Skill ID: outward-copy-quality-gate-humanizer",
    "Skill ID: outward-copy-quality-gate-ogilvy",
)
EXPECTED_PROMPTS = {
    "active": "Rewrite this README title so it is clear and searchable.",
    "silent": "Update the README parser implementation and rerun unit tests.",
}


def item_text(item: object) -> str:
    if not isinstance(item, dict):
        return ""
    content = item.get("content", [])
    if not isinstance(content, list):
        return ""
    return "\n".join(
        part.get("text", "")
        for part in content
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-file", type=Path, required=True)
    parser.add_argument("--request-index", type=int, required=True)
    parser.add_argument("--expect", choices=("active", "silent"), required=True)
    args = parser.parse_args()
    requests = [
        json.loads(line)
        for line in args.capture_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.request_index >= len(requests):
        raise SystemExit(
            f"missing request index {args.request_index}; captured {len(requests)}"
        )
    request = requests[args.request_index]
    inputs = request.get("input", []) if isinstance(request, dict) else []
    if not isinstance(inputs, list):
        raise SystemExit("captured request has no input list")
    user_texts = [
        item_text(item)
        for item in inputs
        if isinstance(item, dict) and item.get("role") == "user"
    ]
    if EXPECTED_PROMPTS[args.expect] not in user_texts:
        raise SystemExit("captured request is missing the exact user prompt")
    developer_texts = [
        item_text(item)
        for item in inputs
        if isinstance(item, dict) and item.get("role") == "developer"
    ]
    serialized = json.dumps(developer_texts, separators=(",", ":"))
    if args.expect == "silent":
        found = [marker for marker in ROUTE_MARKERS if marker in serialized]
        if found:
            raise SystemExit(f"unrelated prompt received copy routing: {found}")
        return 0

    route_contexts = [
        text for text in developer_texts if ROUTE_MARKERS[0] in text
    ]
    if len(route_contexts) != 1:
        raise SystemExit("real Codex request is missing active hook context")
    route_context = route_contexts[0]
    positions = [route_context.find(marker) for marker in EXPECTED_SKILL_ORDER]
    if any(position < 0 for position in positions):
        raise SystemExit("real Codex request is missing a bundled skill")
    if positions != sorted(positions) or len(set(positions)) != len(positions):
        raise SystemExit("real Codex request has the wrong bundled-skill order")
    if "No receipt or marker is required." not in route_context:
        raise SystemExit("real Codex request is missing the nonblocking contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
