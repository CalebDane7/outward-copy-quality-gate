# Outward Copy Quality Gate for Codex

[![Latest Codex compatibility](https://github.com/CalebDane7/outward-copy-quality-gate/actions/workflows/latest-codex-compatibility.yml/badge.svg)](https://github.com/CalebDane7/outward-copy-quality-gate/actions/workflows/latest-codex-compatibility.yml)

This plugin makes Codex use the right writing skills for public-facing copy. It covers titles, headlines, README text, SEO wording, public docs, repository descriptions, marketing copy, onboarding, and UI/help text.

When a request matches, the plugin gives Codex three bundled instructions in order: the copy router, Humanizer, and Ogilvy. It routes the skills in the same turn. It never blocks the prompt or stops Codex from finishing.

If the plugin is missing a file or an update replaces its old cache folder, it tells Codex how to continue safely. The loaded command looks for the newest valid installed version. A plugin failure returns guidance, not a blocked turn.

## Install

Add this repository as a Codex marketplace, then install `outward-copy-quality-gate`. You can use the plugin screen in the Codex app or the matching `codex plugin marketplace add` and `codex plugin add` commands in the terminal.

After installation:

1. Enable the plugin.
2. Open `/hooks`, review the command, and trust it.
3. Start a new chat or CLI session.
4. Try: `Rewrite this README title so it is clear and searchable.`

Run the local checks with:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 python3 plugins/outward-copy-quality-gate/scripts/validate_package.py
```

## What it can and cannot enforce

The hook can put the exact skill instructions in front of Codex. Codex does not expose a skill-completion event, so the plugin cannot prove that a model followed each instruction perfectly. Publication and CI controls still belong in the project that publishes the copy.
