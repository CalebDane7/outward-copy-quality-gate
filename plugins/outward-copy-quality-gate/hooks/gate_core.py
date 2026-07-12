#!/usr/bin/env python3
"""Deterministic, privacy-safe core for the outward-copy hook pair."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STATE_SCHEMA = "outward-copy-quality-gate/state/v1"
MARKER_PREFIX = "outward-copy-quality-gate"
HEX_64_RE = re.compile(r"^[a-f0-9]{64}$")
SAFE_EVIDENCE_RE = re.compile(
    r"^(owner|humanizer|ogilvy):[a-z0-9][a-z0-9._-]{1,63}$"
)
MARKER_RE = re.compile(
    r"<!--\s*outward-copy-quality-gate\s*:\s*(\{.*?\})\s*-->",
    re.DOTALL,
)
MAX_EVENT_BYTES = 2 * 1024 * 1024
MAX_SKILL_BYTES = 32 * 1024
MAX_TOTAL_SKILL_BYTES = 64 * 1024
UNSAFE_SKILL_CONTENT_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9._-])/home/[A-Za-z0-9._-]+(?:/|\b)"),
    re.compile(r"(?i)(?<![A-Za-z0-9])(?:[a-z]:\\Users\\)[^\\\s]+"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|"
        r"client[_ -]?secret|password)\s*[:=]\s*[\"']?[^\s\"']{8,}"
    ),
)

SCOPE_ORDER = (
    "title_headline",
    "readme",
    "seo_search",
    "public_docs",
    "repository_metadata",
    "marketing_sales",
    "product_ui_help",
    "general_outward_copy",
)

# WHY: the old failure used ordinary language ("make ... title more searchable"),
# so the classifier keys on the requested writing action plus the public surface,
# not on an agent remembering to call a skill. Tests pin that exact sentence.
ACTION_RE = re.compile(
    r"\b(?:write|rewrite|draft|create|craft|edit|revise|improve|polish|"
    r"optimi[sz]e|make|change|update|rename|suggest|propose|shorten|tighten|"
    r"humanize|review|audit|fix|refresh|prepare|publish|ship|give me|i need|"
    r"help me (?:write|rewrite|edit|improve|name|draft))\b",
    re.IGNORECASE,
)
QUALITY_INTENT_RE = re.compile(
    r"\b(?:copywriting|copy edit|wording|more searchable|searchable|findable|"
    r"discoverable|better title|stronger headline|plain english|persuasive|"
    r"clearer|more concise|punchier|natural sounding|human[- ]sounding|"
    r"what (?:title|headline|tagline|name) should|is this (?:title|headline|"
    r"copy|description).{0,24}(?:good|clear|strong))\b",
    re.IGNORECASE,
)
CODE_TITLE_RE = re.compile(
    r"(?:document\.title|window title|terminal title|title attribute|"
    r"<title>|titlebar|title bar)",
    re.IGNORECASE,
)
FACTUAL_AUDIT_RE = re.compile(
    r"\b(?:fact[- ]check|factual accuracy|verify (?:the )?facts?|broken links?|"
    r"source citations?|citation accuracy)\b",
    re.IGNORECASE,
)
CODE_COPY_OPERATION_RE = re.compile(
    r"\b(?:(?:copy|website[ _-]?copy)\s+(?:function|method|class|variable)|"
    r"(?:function|method|class|variable)\s+(?:named\s+)?[a-z0-9_]*copy[a-z0-9_]*)\b",
    re.IGNORECASE,
)
COPY_QUALIFIER_RE = re.compile(
    r"\b(?:seo|searchable|wording|copy|headline|tagline|description|topics?|"
    r"public|reader|persuasive|human|punchy|concise|rewrite|draft|write)\b",
    re.IGNORECASE,
)

SCOPE_PATTERNS = {
    "title_headline": re.compile(
        r"\b(?:title|headline|subhead(?:ing)?|subtitle|tagline|slogan|"
        r"product name|project name|feature name)\b",
        re.IGNORECASE,
    ),
    "readme": re.compile(r"\breadme(?:\.md)?\b", re.IGNORECASE),
    "seo_search": re.compile(
        r"\b(?:seo|searchable|search wording|search terms?|search keywords?|"
        r"keywords?|discoverable|findable|search ranking|search snippet|"
        r"meta description)\b",
        re.IGNORECASE,
    ),
    "public_docs": re.compile(
        r"\b(?:public (?:docs?|documentation)|user (?:docs?|guide|manual)|"
        r"help (?:text|copy|article|page|center)|documentation for (?:users|"
        r"customers)|release notes?|changelog copy|getting started guide|"
        r"customer[- ]facing (?:faq|frequently asked questions?))\b",
        re.IGNORECASE,
    ),
    "repository_metadata": re.compile(
        r"\b(?:(?:github|gitlab|repository|repo|package|project)\s+"
        r"(?:title|description|topics?|metadata|about)|(?:description|topics?)\s+"
        r"for (?:the |this |my )?(?:github|gitlab|repository|repo|package))\b",
        re.IGNORECASE,
    ),
    "marketing_sales": re.compile(
        r"\b(?:marketing copy|sales copy|landing page|home ?page copy|"
        r"pricing page|product page|feature page|value proposition|"
        r"launch announcement|press release|ad copy|advertisement|campaign|"
        r"sales email|cold email|email sequence|social (?:post|copy|caption)|"
        r"product description|brand copy|positioning statement|website copy|"
        r"newsletters?|public announcements?|app[- ]store description|about page|"
        r"customer case stud(?:y|ies))\b",
        re.IGNORECASE,
    ),
    "product_ui_help": re.compile(
        r"\b(?:onboarding copy|welcome message|button label|ui copy|ux copy|"
        r"tooltip|empty state|error message|validation message|in-app help|"
        r"user-facing (?:text|copy|message|label|words)|dialog copy|modal copy|"
        r"notification copy)\b",
        re.IGNORECASE,
    ),
    # WHY: explicit publish-ready copy and public/customer-facing messages need
    # a bounded fallback without turning private notes, code, or factual audits
    # into copywriting work. Positive and disconfirming fixtures pin this edge.
    "general_outward_copy": re.compile(
        r"\b(?:customer support emails?|(?:this|the|our|my)\s+copy\s+before\s+"
        r"(?:i|we)\s+publish(?:\s+it)?|(?:this|the|our|my)\s+"
        r"(?:public|customer)[- ]facing\s+(?:message|copy|text|content))\b",
        re.IGNORECASE,
    ),
}


class GateError(RuntimeError):
    """A safe error code that never includes prompt or copy text."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_stdin_event() -> dict[str, Any]:
    raw = sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
    if not raw or len(raw) > MAX_EVENT_BYTES:
        raise GateError("invalid_hook_input")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError("invalid_hook_input") from exc
    if not isinstance(payload, dict):
        raise GateError("invalid_hook_input")
    return payload


def require_plugin_root() -> Path:
    raw = os.environ.get("PLUGIN_ROOT", "")
    if not raw:
        raise GateError("plugin_root_missing")
    root = Path(raw).resolve()
    if not (root / ".codex-plugin" / "plugin.json").is_file():
        raise GateError("plugin_root_invalid")
    return root


def require_plugin_data() -> Path:
    raw = os.environ.get("PLUGIN_DATA", "")
    if not raw:
        raise GateError("plugin_data_missing")
    root = Path(raw).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def load_policy(plugin_root: Path) -> tuple[dict[str, Any], str]:
    path = plugin_root / "policy" / "outward-copy-policy.json"
    try:
        raw = path.read_bytes()
        policy = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError("policy_unavailable") from exc
    if not isinstance(policy, dict):
        raise GateError("policy_invalid")
    return policy, sha256_bytes(raw)


def classify_prompt(prompt: str) -> list[str]:
    if not isinstance(prompt, str) or not prompt.strip():
        return []
    has_intent = bool(ACTION_RE.search(prompt) or QUALITY_INTENT_RE.search(prompt))
    if not has_intent:
        return []
    if CODE_TITLE_RE.search(prompt) and not COPY_QUALIFIER_RE.search(prompt):
        return []
    if CODE_COPY_OPERATION_RE.search(prompt):
        return []
    if FACTUAL_AUDIT_RE.search(prompt) and not QUALITY_INTENT_RE.search(prompt):
        return []

    matched = [
        scope for scope in SCOPE_ORDER if SCOPE_PATTERNS[scope].search(prompt)
    ]

    # GitHub title requests are repository metadata even when the user does not
    # use the word "description". This is the exact owner-layer gap from the old
    # failure and is protected by a fixture.
    if (
        "title_headline" in matched
        and re.search(r"\b(?:github|gitlab|repository|repo|package)\b", prompt, re.I)
        and "repository_metadata" not in matched
    ):
        matched.append("repository_metadata")

    return [scope for scope in SCOPE_ORDER if scope in matched]


def turn_key(session_id: str, turn_id: str) -> str:
    return sha256_text(f"{session_id}\x00{turn_id}")


def load_skill_materials(
    plugin_root: Path, policy: dict[str, Any]
) -> list[dict[str, str]]:
    materials: list[dict[str, str]] = []
    skills = policy.get("skills")
    if not isinstance(skills, list) or len(skills) != 3:
        raise GateError("policy_skill_contract_invalid")
    seen_ids: set[str] = set()
    total_bytes = 0
    for entry in skills:
        if not isinstance(entry, dict):
            raise GateError("policy_skill_contract_invalid")
        skill_id = entry.get("id")
        relative = entry.get("path")
        if (
            not isinstance(skill_id, str)
            or not isinstance(relative, str)
            or skill_id in seen_ids
            or Path(relative).is_absolute()
        ):
            raise GateError("policy_skill_contract_invalid")
        seen_ids.add(skill_id)
        path = (plugin_root / relative).resolve()
        try:
            path.relative_to(plugin_root)
        except ValueError as exc:
            raise GateError("policy_skill_path_invalid") from exc
        if path.name != "SKILL.md" or not path.is_file():
            raise GateError("required_skill_missing")
        path_text = str(path)
        if any(ord(character) < 32 for character in path_text):
            raise GateError("required_skill_path_unsafe")
        try:
            with path.open("rb") as handle:
                raw = handle.read(MAX_SKILL_BYTES + 1)
        except OSError as exc:
            raise GateError("required_skill_unreadable") from exc
        if not raw:
            raise GateError("required_skill_empty")
        if len(raw) > MAX_SKILL_BYTES:
            raise GateError("required_skill_oversized")
        total_bytes += len(raw)
        if total_bytes > MAX_TOTAL_SKILL_BYTES:
            raise GateError("required_skills_oversized")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GateError("required_skill_invalid_utf8") from exc
        if any(
            ord(character) < 32 and character not in "\n\r\t"
            for character in content
        ):
            raise GateError("required_skill_content_unsafe")
        if any(pattern.search(content) for pattern in UNSAFE_SKILL_CONTENT_PATTERNS):
            raise GateError("required_skill_content_unsafe")
        frontmatter = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
        if not frontmatter or not re.search(
            rf"(?m)^name:\s*{re.escape(skill_id)}\s*$", frontmatter.group(1)
        ):
            raise GateError("required_skill_identity_invalid")
        materials.append(
            {
                "id": skill_id,
                "path": path_text,
                "sha256": sha256_bytes(raw),
                "content": content,
            }
        )
    return materials


def records_from_materials(
    materials: Iterable[dict[str, str]],
) -> list[dict[str, str]]:
    return [
        {"id": material["id"], "sha256": material["sha256"]}
        for material in materials
    ]


def skill_records(plugin_root: Path, policy: dict[str, Any]) -> list[dict[str, str]]:
    return records_from_materials(load_skill_materials(plugin_root, policy))


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise GateError("private_state_write_failed") from exc


def read_private_json(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_EVENT_BYTES:
            raise GateError("private_state_invalid")
        value = json.loads(path.read_text(encoding="utf-8"))
    except GateError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError("private_state_invalid") from exc
    if not isinstance(value, dict):
        raise GateError("private_state_invalid")
    return value


def state_path(plugin_data: Path, key: str) -> Path:
    return plugin_data / "turn-state" / f"{key}.json"


def receipt_path(plugin_data: Path, key: str) -> Path:
    return plugin_data / "receipts" / f"{key}.json"


def new_turn_state(
    *,
    policy: dict[str, Any],
    policy_sha256: str,
    session_id: str,
    turn_id: str,
    prompt: str,
    scopes: list[str],
    skills: list[dict[str, str]],
) -> dict[str, Any]:
    if not session_id or not turn_id:
        raise GateError("turn_identity_missing")
    expected_scopes = policy.get("required_scopes")
    if not isinstance(expected_scopes, list) or any(scope not in expected_scopes for scope in scopes):
        raise GateError("policy_scope_contract_invalid")
    return {
        "schema": STATE_SCHEMA,
        "policy_id": policy.get("policy_id"),
        "plugin_version": policy.get("plugin_version"),
        "marker_schema": policy.get("marker_schema"),
        "receipt_schema": policy.get("receipt_schema"),
        "turn_key": turn_key(session_id, turn_id),
        "prompt_sha256": sha256_text(prompt),
        "policy_sha256": policy_sha256,
        "scopes": scopes,
        "turn_nonce": secrets.token_urlsafe(24),
        "skills": skills,
        "created_at": utc_now(),
        "status": "pending",
    }


def marker_template(state: dict[str, Any]) -> str:
    skills = {item["id"]: item["sha256"] for item in state["skills"]}
    marker = {
        "schema": state["marker_schema"],
        "turn_nonce": state["turn_nonce"],
        "prompt_sha256": state["prompt_sha256"],
        "copy_owner_evidence": "owner:<safe-id>",
        "humanizer_evidence": "humanizer:<safe-id>",
        "ogilvy_evidence": "ogilvy:<safe-id>",
        "router_skill_sha256": skills["outward-copy-quality-gate-router"],
        "humanizer_skill_sha256": skills["outward-copy-quality-gate-humanizer"],
        "ogilvy_skill_sha256": skills["outward-copy-quality-gate-ogilvy"],
    }
    return f"<!-- {MARKER_PREFIX}: {json.dumps(marker, sort_keys=True, separators=(',', ':'))} -->"


def additional_context(
    state: dict[str, Any], materials: list[dict[str, str]]
) -> str:
    if records_from_materials(materials) != state.get("skills"):
        raise GateError("required_skill_changed_during_context")
    scope_text = ", ".join(state["scopes"])
    skill_sections: list[str] = []
    for index, material in enumerate(materials, start=1):
        skill_sections.append(
            f"BEGIN BUNDLED SKILL {index}/{len(materials)}\n"
            f"Skill ID: {material['id']}\n"
            f"Resolved SKILL.md path: {material['path']}\n"
            f"SHA-256: {material['sha256']}\n"
            "Bounded, privacy-checked SKILL.md contents:\n"
            f"{material['content'].rstrip()}\n"
            f"END BUNDLED SKILL {index}/{len(materials)}"
        )
    return (
        "OUTWARD COPY QUALITY GATE ACTIVE.\n"
        f"Matched scopes: {scope_text}.\n"
        "The three exact bundled SKILL.md files are injected below in deterministic "
        "policy order because same-named catalog skills may be absent or ambiguous. "
        "Use these injected paths and contents on the same candidate; do not resolve "
        "a same-named catalog entry instead. "
        "Complete the designated copy-owner pass, then the Humanizer pass, then the "
        "Ogilvy pass. The receipt declares those passes but cannot prove their semantic "
        "execution, so do not claim a pass that did not happen. At the end of the final "
        "assistant message, append exactly one receipt comment from the template below.\n\n"
        + "\n\n".join(skill_sections)
        + "\n\n"
        "Replace only the three <safe-id> placeholders with short lowercase evidence IDs. "
        "Never put prompt text, copy text, credentials, names, or private context in the marker.\n"
        f"{marker_template(state)}"
    )


def parse_marker(message: str) -> tuple[dict[str, Any], re.Match[str]]:
    matches = list(MARKER_RE.finditer(message))
    if len(matches) != 1:
        raise GateError("receipt_marker_missing_or_duplicated")
    match = matches[0]
    try:
        marker = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise GateError("receipt_marker_invalid_json") from exc
    if not isinstance(marker, dict):
        raise GateError("receipt_marker_invalid_shape")
    return marker, match


def _expected_marker_keys() -> set[str]:
    return {
        "schema",
        "turn_nonce",
        "prompt_sha256",
        "copy_owner_evidence",
        "humanizer_evidence",
        "ogilvy_evidence",
        "router_skill_sha256",
        "humanizer_skill_sha256",
        "ogilvy_skill_sha256",
    }


def validate_marker(
    marker: dict[str, Any],
    state: dict[str, Any],
    current_policy_sha256: str,
    current_skills: list[dict[str, str]],
) -> None:
    for field in (
        "copy_owner_evidence",
        "humanizer_evidence",
        "ogilvy_evidence",
    ):
        if field not in marker:
            raise GateError(f"{field}_missing_or_invalid")
    if set(marker) != _expected_marker_keys():
        raise GateError("receipt_marker_fields_invalid")
    if marker.get("schema") != state.get("marker_schema"):
        raise GateError("receipt_marker_schema_mismatch")
    nonce = marker.get("turn_nonce")
    expected_nonce = state.get("turn_nonce")
    if not isinstance(nonce, str) or not isinstance(expected_nonce, str):
        raise GateError("receipt_turn_binding_invalid")
    if not hmac.compare_digest(nonce, expected_nonce):
        raise GateError("receipt_turn_binding_invalid")
    prompt_hash = marker.get("prompt_sha256")
    if not isinstance(prompt_hash, str) or not hmac.compare_digest(
        prompt_hash, str(state.get("prompt_sha256", ""))
    ):
        raise GateError("receipt_prompt_binding_invalid")
    if current_policy_sha256 != state.get("policy_sha256"):
        raise GateError("policy_changed_during_turn")

    evidence_contract = {
        "copy_owner_evidence": "owner:",
        "humanizer_evidence": "humanizer:",
        "ogilvy_evidence": "ogilvy:",
    }
    for field, prefix in evidence_contract.items():
        value = marker.get(field)
        if not isinstance(value, str) or not SAFE_EVIDENCE_RE.fullmatch(value):
            raise GateError(f"{field}_missing_or_invalid")
        if not value.startswith(prefix):
            raise GateError(f"{field}_missing_or_invalid")

    hashes = {item["id"]: item["sha256"] for item in current_skills}
    expected_hash_fields = {
        "router_skill_sha256": hashes.get("outward-copy-quality-gate-router"),
        "humanizer_skill_sha256": hashes.get("outward-copy-quality-gate-humanizer"),
        "ogilvy_skill_sha256": hashes.get("outward-copy-quality-gate-ogilvy"),
    }
    state_hashes = {item["id"]: item["sha256"] for item in state.get("skills", [])}
    for field, expected in expected_hash_fields.items():
        value = marker.get(field)
        skill_id = field.removesuffix("_skill_sha256")
        state_id = {
            "router": "outward-copy-quality-gate-router",
            "humanizer": "outward-copy-quality-gate-humanizer",
            "ogilvy": "outward-copy-quality-gate-ogilvy",
        }[skill_id]
        if not isinstance(value, str) or not HEX_64_RE.fullmatch(value):
            raise GateError("receipt_skill_binding_invalid")
        if value != expected or value != state_hashes.get(state_id):
            raise GateError("receipt_skill_binding_invalid")


def message_without_marker(message: str, match: re.Match[str]) -> str:
    return (message[: match.start()] + message[match.end() :]).rstrip()


RECEIPT_REQUIRED_FIELDS = {
    "schema",
    "policy_id",
    "plugin_version",
    "status",
    "turn_key",
    "prompt_sha256",
    "output_sha256",
    "policy_sha256",
    "scopes",
    "copy_owner_evidence",
    "humanizer_evidence",
    "ogilvy_evidence",
    "skills",
    "created_at",
    "validated_at",
}


def build_receipt(
    *, state: dict[str, Any], marker: dict[str, Any], message: str, match: re.Match[str]
) -> dict[str, Any]:
    return {
        "schema": state["receipt_schema"],
        "policy_id": state["policy_id"],
        "plugin_version": state["plugin_version"],
        "status": "validated",
        "turn_key": state["turn_key"],
        "prompt_sha256": state["prompt_sha256"],
        "output_sha256": sha256_text(message_without_marker(message, match)),
        "policy_sha256": state["policy_sha256"],
        "scopes": state["scopes"],
        "copy_owner_evidence": marker["copy_owner_evidence"],
        "humanizer_evidence": marker["humanizer_evidence"],
        "ogilvy_evidence": marker["ogilvy_evidence"],
        "skills": state["skills"],
        "created_at": state["created_at"],
        "validated_at": utc_now(),
    }


def validate_receipt_shape(
    receipt: dict[str, Any], policy: dict[str, Any], current_skills: Iterable[dict[str, str]]
) -> list[str]:
    errors: list[str] = []
    if set(receipt) != RECEIPT_REQUIRED_FIELDS:
        errors.append("receipt_fields_invalid")
    expected_scalars = {
        "schema": policy.get("receipt_schema"),
        "policy_id": policy.get("policy_id"),
        "plugin_version": policy.get("plugin_version"),
        "status": "validated",
    }
    for field, expected in expected_scalars.items():
        if receipt.get(field) != expected:
            errors.append(f"{field}_invalid")
    for field in ("turn_key", "prompt_sha256", "output_sha256", "policy_sha256"):
        if not isinstance(receipt.get(field), str) or not HEX_64_RE.fullmatch(receipt[field]):
            errors.append(f"{field}_invalid")
    scopes = receipt.get("scopes")
    valid_scopes = policy.get("required_scopes", [])
    if (
        not isinstance(scopes, list)
        or not scopes
        or len(scopes) != len(set(scopes))
        or any(scope not in valid_scopes for scope in scopes)
    ):
        errors.append("scopes_invalid")
    for field, prefix in (
        ("copy_owner_evidence", "owner:"),
        ("humanizer_evidence", "humanizer:"),
        ("ogilvy_evidence", "ogilvy:"),
    ):
        value = receipt.get(field)
        if (
            not isinstance(value, str)
            or not SAFE_EVIDENCE_RE.fullmatch(value)
            or not value.startswith(prefix)
        ):
            errors.append(f"{field}_invalid")
    if receipt.get("skills") != list(current_skills):
        errors.append("skills_invalid")
    for field in ("created_at", "validated_at"):
        if not isinstance(receipt.get(field), str) or not receipt[field]:
            errors.append(f"{field}_invalid")
    return sorted(set(errors))


def safe_repair_reason(code: str) -> str:
    gate_names = {
        "copy_owner_evidence_missing_or_invalid": "copy-owner evidence is missing",
        "humanizer_evidence_missing_or_invalid": "Humanizer evidence is missing",
        "ogilvy_evidence_missing_or_invalid": "Ogilvy evidence is missing",
    }
    issue = gate_names.get(code, "the same-turn receipt is missing, stale, or invalid")
    return (
        f"Outward copy needs one repair pass because {issue}. Use the three exact "
        "bundled skills named in the injected gate context, complete the copy-owner, "
        "Humanizer, and Ogilvy reviews on the final candidate, then append one "
        "privacy-safe receipt comment from that template. Do not put prompt or copy "
        "text in the marker."
    )
