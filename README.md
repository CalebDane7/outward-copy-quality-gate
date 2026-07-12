# Outward Copy Quality Gate for Codex

This plugin catches public-copy requests that Codex can otherwise treat as ordinary editing. It covers titles, headlines, README text, SEO wording, public docs, repository descriptions and topics, website and About-page copy, newsletters, public announcements, app-store descriptions, customer support emails, customer-facing FAQs and case studies, marketing, onboarding, UI/help text, and explicit generic requests to polish copy for publication or clarify a public-facing message.

For a matching request, the prompt hook injects the exact resolved paths and bounded contents of three bundled stages: a designated copy owner, a natural-language edit, and a plain-English persuasion review. The Stop hook requires a privacy-safe, same-turn, hash-bound declaration and receipt before the turn finishes. If one declared evidence entry is missing, Codex gets one focused repair pass. This verifies the record, not whether the model semantically performed each stage.

The plugin stores hashes, matched scope names, timestamps, and short evidence IDs under `PLUGIN_DATA`. It does not store the raw prompt or copy.

## Install

Add this repository as a Codex marketplace, then install `outward-copy-quality-gate` from the `outward-copy-quality-gate` marketplace. You can use the plugin screen in the Codex app or the matching `codex plugin marketplace add` and `codex plugin add` commands in the terminal.

After installation:

1. Enable the plugin.
2. Open `/hooks`, review both commands, and trust them.
3. Start a new chat or CLI session.
4. Try: `Rewrite this README title so it is clear and searchable.`

Run the local checks with:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 python3 plugins/outward-copy-quality-gate/scripts/validate_package.py
```

## What the receipt proves

The receipt binds the current prompt hash, final output hash, matched scopes, plugin policy, and exact bundled skill hashes. It also records short evidence IDs for the three required stages. It contains no prompt or copy body.

The receipt is a routing and review record. Codex has no native hook that can prove a skill was semantically applied, so the evidence IDs still depend on the agent reporting its work honestly. See [current limits](docs/limitations.md) and the [receipt format](docs/receipt-format.md).
