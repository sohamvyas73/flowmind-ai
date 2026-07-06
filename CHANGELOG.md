# Changelog

## Unreleased

### Security

- **Code Runner disabled by default.** The `codeNode` no longer executes user Python unless `ENABLE_CODE_NODE=true` is set explicitly. This closes an in-process sandbox escape / RCE risk.

### Changed

- When `ENABLE_CODE_NODE=false`, existing workflows that contain a Code Runner node **continue to run**: the node is skipped and upstream data is passed through to downstream nodes. Workflows are not aborted.
- `/health` now includes `features.code_node` so the UI can reflect whether Code Runner is available.

### Upgrade notes

1. Add `ENABLE_CODE_NODE=false` to your environment (see `backend/.env.example`). This is the new secure default.
2. On startup, the API logs a warning listing any saved workflows that still contain `codeNode` when the flag is off.
3. To restore Code Runner execution (development / trusted sandbox only), set `ENABLE_CODE_NODE=true` and restart the backend.
