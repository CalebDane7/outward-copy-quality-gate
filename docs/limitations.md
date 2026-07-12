# Current limits

- Plugin hooks must be enabled and trusted on each Codex installation. An administrator can disable them.
- `UserPromptSubmit` and `Stop` cover chat and file-edit copy without depending on a particular tool. They do not control writers outside Codex.
- Codex does not currently expose a skill-lifecycle hook. The receipt proves that the required stages were declared and bound to the same turn, not that a model performed each semantic review perfectly.
- The Stop hook requests one repair pass. It honors `stop_hook_active` and will not create an endless continuation loop.
- Direct GitHub metadata changes, website publishing, and merges need their own required CI or guarded publisher if they must be impossible to bypass.
- Changed non-managed hook commands must be reviewed and trusted again.

These limits are why the package calls itself a quality gate, not a security boundary.
