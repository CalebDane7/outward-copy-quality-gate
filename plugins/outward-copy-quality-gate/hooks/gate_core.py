#!/usr/bin/env python3
"""Deterministic, privacy-safe routing for outward-copy prompts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


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

EXPECTED_SKILL_CONTRACT = (
    (
        "router",
        "outward-copy-quality-gate-router",
        "skills/outward-copy-quality-gate-router/SKILL.md",
    ),
    (
        "humanizer",
        "outward-copy-quality-gate-humanizer",
        "skills/outward-copy-quality-gate-humanizer/SKILL.md",
    ),
    (
        "ogilvy",
        "outward-copy-quality-gate-ogilvy",
        "skills/outward-copy-quality-gate-ogilvy/SKILL.md",
    ),
)

# WHY: the original missed request used ordinary wording such as "make the
# title more searchable". Routing therefore combines a writing action with a
# reader-facing surface instead of relying on the model to remember a skill.
ACTION_RE = re.compile(
    r"\b(?:write|rewrite|draft|compose|create|craft|edit|revise|improve|polish|"
    r"optimi[sz]e|make|change|update|rename|suggest|propose|shorten|tighten|"
    r"humanize|review|audit|fix|refresh|prepare|publish|ship|clean up|give|"
    r"give me|i need|proofread|respond|come up with|"
    r"help me (?:write|rewrite|edit|improve|name|draft))\b",
    re.IGNORECASE,
)
QUALITY_INTENT_RE = re.compile(
    r"\b(?:copywriting|copy edit|wording|more searchable|searchable|findable|"
    r"discoverable|better title|stronger headline|plain english|persuasive|"
    r"clearer|more concise|punchier|natural sounding|human[- ]sounding|"
    r"typos?|spelling|grammar|better label|copy for|to say|text users see|"
    r"what (?:title|headline|tagline|name) should|is this (?:title|headline|"
    r"copy|description).{0,24}(?:good|clear|strong))\b",
    re.IGNORECASE,
)
STRONG_COPY_ACTION_RE = re.compile(
    r"\b(?:write|rewrite|draft|craft|edit|revise|improve|polish|tighten|"
    r"shorten|humanize|clean up)\b.{0,60}\b(?:copy|wording)\b",
    re.IGNORECASE,
)
ENGINEERING_CONTEXT_RE = re.compile(
    r"\b(?:bug|parser|implementation|unit tests?|tests?|component|react|"
    r"generator|renderer|rendering|sending job|job|daemon|service|source code|"
    r"code|sync|function|method|class|variable|endpoint|api|checker|"
    r"link checker|ci|workflow|css|stylesheet|layout|responsive|build|"
    r"pipeline|compile|compiler|deploy|deployment|position|placement|"
    r"locali[sz]ation|i18n|resource key|database|schema|field|logs?|logging)\b",
    re.IGNORECASE,
)
COPY_CONTENT_OVERRIDE_RE = re.compile(
    r"\b(?:typos?|spelling|grammar|copy for|to say|text users see|"
    r"respond to (?:a |the )?customer|label for (?:the )?.{0,30}button)\b|"
    r"\b(?:write|rewrite|draft|compose|craft|edit|revise|polish|proofread|"
    r"humanize|clean up)\b.{0,80}\b(?:error (?:message|text)|button "
    r"(?:label|text)|tooltip|empty state|faq|press release|linkedin post|"
    r"customer (?:complaint|email))\b|"
    r"\b(?:error (?:message|text)|button (?:label|text)|copy|wording|"
    r"headline|tagline|description)\b.{0,50}\b(?:clearer|more concise|"
    r"punchier|natural sounding|human[- ]sounding|plain english)\b",
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
        r"(?:docs?|documentation) for (?:users|customers)|customer (?:docs?|"
        r"documentation)|"
        r"help (?:text|copy|article|page|center)|documentation for (?:users|"
        r"customers)|release notes?|changelog copy|getting started guide|"
        r"customer[- ]facing (?:faq|frequently asked questions?)|"
        r"(?:faq|frequently asked questions?) for (?:(?:our|the) )?"
        r"(?:users|customers))\b",
        re.IGNORECASE,
    ),
    "repository_metadata": re.compile(
        r"\b(?:(?:github|gitlab|repository|repo|package|project)\s+"
        r"(?:title|description|topics?|metadata|about)|(?:description|topics?)\s+"
        r"for (?:the |this |my )?(?:github|gitlab|repository|repo|package))\b",
        re.IGNORECASE,
    ),
    "marketing_sales": re.compile(
        r"\b(?:marketing copy|sales copy|landing page|home ?page(?: copy| hero)?|"
        r"hero (?:copy|text|headline)|"
        r"pricing page|product page|feature page|value proposition|"
        r"launch announcement|press release|ad copy|advertisement|campaign|"
        r"sales email|cold email|email sequence|social (?:post|copy|caption)|"
        r"product description|brand copy|positioning statement|website copy|"
        r"newsletters?|public announcements?|app[- ]store description|about page|"
        r"customer case stud(?:y|ies)|linkedin (?:post|article|caption)|"
        r"(?:sign ?up|registration) page)\b",
        re.IGNORECASE,
    ),
    "product_ui_help": re.compile(
        r"\b(?:onboarding copy|welcome message|button (?:label|text)|ui copy|ux copy|"
        r"tooltip|empty state|error (?:message|text)|validation message|in-app help|"
        r"user-facing (?:text|copy|message|label|words)|dialog copy|modal copy|"
        r"notification copy|(?:sign ?up|checkout|submit|payment) button|"
        r"label for (?:the )?.{0,30}button|text users see when .{0,50}|"
        r"payment (?:fails?|failure|failed) (?:message|text)?)\b",
        re.IGNORECASE,
    ),
    "general_outward_copy": re.compile(
        r"\b(?:customer support emails?|(?:apology|support|customer service)\s+"
        r"emails?(?:\s+to\s+customers)?|emails?\s+to\s+customers|"
        r"(?:this|the|our|my)\s+(?:release\s+)?copy\s+before\s+"
        r"(?:(?:i|we)\s+)?publish(?:ing|ed)?(?:\s+it)?|release copy|"
        r"(?:this|the|our|my)\s+"
        r"(?:public|customer)[- ]facing\s+(?:message|copy|text|content)|"
        r"(?:respond|response) to (?:a |the )?customer complaint|"
        r"customer complaint response)\b",
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
    if ENGINEERING_CONTEXT_RE.search(prompt) and not (
        STRONG_COPY_ACTION_RE.search(prompt) or COPY_CONTENT_OVERRIDE_RE.search(prompt)
    ):
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
    if (
        "title_headline" in matched
        and re.search(r"\b(?:github|gitlab|repository|repo|package)\b", prompt, re.I)
        and "repository_metadata" not in matched
    ):
        matched.append("repository_metadata")
    return [scope for scope in SCOPE_ORDER if scope in matched]


def load_skill_materials(
    plugin_root: Path, policy: dict[str, Any]
) -> list[dict[str, str]]:
    materials: list[dict[str, str]] = []
    skills = policy.get("skills")
    if not isinstance(skills, list) or len(skills) != 3:
        raise GateError("policy_skill_contract_invalid")
    # WHY: routing the right three skills in the wrong order changes the result.
    # Pin the runtime contract as well as the publish validator so cache edits or
    # a bad update degrade visibly instead of silently reordering the reviews.
    skill_contract = tuple(
        (
            entry.get("role"),
            entry.get("id"),
            entry.get("path"),
        )
        if isinstance(entry, dict)
        else (None, None, None)
        for entry in skills
    )
    if skill_contract != EXPECTED_SKILL_CONTRACT:
        raise GateError("policy_skill_order_invalid")
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


def additional_context(
    scopes: list[str], materials: list[dict[str, str]]
) -> str:
    if not scopes or len(materials) != 3:
        raise GateError("routing_context_invalid")
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
        "OUTWARD COPY ROUTE ACTIVE.\n"
        "Continue the current user task. This hook provides same-turn guidance only; "
        "it must not veto the prompt, block completion, or create another turn.\n"
        f"Matched scopes: {', '.join(scopes)}.\n"
        "Apply the exact bundled instructions below to the same candidate in this "
        "order: copy router/owner, Humanizer, then Ogilvy. Preserve facts and "
        "constraints, do not invent claims, and do not claim a review that did not "
        "happen. No receipt or marker is required.\n\n"
        + "\n\n".join(skill_sections)
    )


def degraded_context() -> str:
    return (
        "OUTWARD COPY ROUTING DEGRADED. Continue the current user task; do not stop. "
        "If this is outward-facing copy, apply the installed outward-copy router, "
        "Humanizer, and Ogilvy skills before finalizing. If those skills are not "
        "available, identify the reader and factual constraints, remove canned or "
        "inflated language, lead with the strongest true benefit, and omit unsupported "
        "claims. Repair this plugin with the supported Codex plugin update or reinstall "
        "flow after the current task."
    )
