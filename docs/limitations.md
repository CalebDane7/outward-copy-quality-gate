# Current limits

- Plugin hooks must be enabled and trusted on each Codex installation.
- The plugin routes matching Codex prompts. It does not control writing tools outside Codex.
- Codex does not expose a skill-completion event, so injected instructions cannot prove that each review happened.
- A changed hook command may need a new trust review in a fresh or resumed session.
- Direct publishing, GitHub metadata changes, and merges need their own review or CI controls.
- The daily compatibility check uses the repository's scoped `GITHUB_TOKEN` to maintain deduplicated compatibility issues. Repository policy can deny issue writes, and GitHub can disable schedules after 60 days without public-repository activity; the workflow badge and push-triggered run remain visible fallback signals.
- Supported hosted full-lifecycle checks run on Ubuntu and macOS 15 Intel. A separate daily macOS 15 ARM probe installs the latest Codex, proves the hook contract directly, and attempts the full lifecycle. An ARM lifecycle failure stays visible in a dedicated GitHub issue without hiding the supported results.
- On GitHub's macOS 15 ARM and macOS 26 ARM runners, the bundled hook passes directly, but the current Codex CLI exits before the local mock-provider lifecycle completes. That upstream runner or CLI boundary is not claimed green.
- A real Codex App install, hook-trust review, and first routed turn on another person's Mac still need proof on that Mac.

The default hook is deliberately fail-open. Missing files, stale cache paths, or internal errors may reduce the copy review, but they must never prevent the user's work from continuing.
