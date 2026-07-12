# Receipt format

`UserPromptSubmit` creates a pending turn record under `PLUGIN_DATA`. The record contains a prompt hash, matched scopes, a random turn nonce, the policy hash, and the three bundled skill hashes. It contains no raw prompt.

The hook also gives Codex a one-line HTML comment template. Codex replaces three short placeholders after completing the copy-owner, Humanizer, and Ogilvy passes. Those IDs must use these forms:

```text
owner:short-id
humanizer:short-id
ogilvy:short-id
```

At `Stop`, the plugin checks the marker against the pending turn and current plugin files. A valid marker produces a receipt under `PLUGIN_DATA/receipts`. The Stop hook calculates the final output hash itself after removing the marker, so the agent cannot accidentally bind the receipt to a different draft.

Exported receipts follow [`receipt.schema.json`](../plugins/outward-copy-quality-gate/schemas/receipt.schema.json). Validate one with:

```bash
python3 plugins/outward-copy-quality-gate/scripts/validate_receipt.py \
  --receipt <receipt.json> \
  --message-file <final-message.txt>
```

The validator prints only pass/fail metadata and safe error codes.
