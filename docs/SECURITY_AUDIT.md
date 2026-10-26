# Security audit — status

Findings from the repository audit (originally drafted in PR #2) and how each was addressed.

| # | Severity | Finding | Status |
|---|----------|---------|--------|
| 1 | P0 | In-process Code Runner (`exec`) | **Mitigated.** Off by default (`ENABLE_CODE_NODE`); when on, runs in a separate killable process: empty env, throwaway cwd, CPU/memory/file/process limits, hard kill on timeout, introspection builtins (`getattr`, `hasattr`, `type`) removed. **Not a full sandbox** — the child can still use the network/filesystem as the backend user. Keep disabled unless the backend itself is containerised. |
| 2 | P0 | SSRF via HTTP / custom KYC nodes | **Fixed.** `app/core/url_safety.py`: http(s) only, every resolved IP must be public, redirects re-validated per hop (max 3). `ALLOW_PRIVATE_URLS=true` is a dev-only escape hatch. Residual: DNS-rebinding between check and connect. |
| 3 | P0 | Credits charged after execution, non-atomic | **Fixed.** Estimated cost is atomically reserved (`UPDATE … WHERE credits_used + est <= credits_total`, HTTP 402 otherwise), then settled to actual usage (refunds the difference, also on crashes). |
| 4 | P0 | Raw secrets stored/returned | **Fixed.** Provider keys + node secrets encrypted at rest (Fernet); node secrets live in an encrypted `workflows.secrets` vault and are replaced by `__secret__` in `graph_data`; API tokens stored as SHA-256 hash + prefix and shown once (signup / rotate). Legacy rows migrated at startup (existing users must rotate to see their token again). |
| 5 | P1 | Unredacted traces / KYC responses / logs | **Fixed.** Persisted inputs/outputs/traces are redacted (keys, KYC raw responses, document numbers); `raw_response` dropped from KYC output; prompts/model outputs/results no longer logged; `EXECUTION_RETENTION_DAYS` purge. Trigger API callers still receive the live output. |
| 6 | P1 | DB session held during long runs | **Fixed.** Session is closed before the workflow runs; a fresh session records the result and billing. |
| 7 | P1 | Auth: inactive 401, JWT expiry ignored, no rate limits | **Fixed.** Inactive → 403; `ACCESS_TOKEN_EXPIRE_MINUTES` honoured; per-IP and per-account auth limits plus per-user run limits (in-memory, per process — use a shared limiter behind multiple workers); optional `API_TOKEN_TTL_DAYS`. |
| 8 | P1 | Verification / decision routing | **Fixed.** Verification reports the model's real verdict; decision requires an explicit `approved`/`rejected` JSON label, enforces the confidence threshold, and fails closed (rejected) on malformed output. |

Tests: `cd backend && pip install -r requirements.txt -r requirements-dev.txt && pytest`.
