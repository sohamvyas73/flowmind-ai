# Security Audit Issue Drafts

## P0: Replace or Disable In-Process Code Runner Execution

**Impact:** Authenticated workflow authors can execute arbitrary Python through the Code Runner node. The current restricted `__builtins__` approach is bypassable through Python object introspection and can lead to host remote code execution.

**Evidence:** `backend/app/services/workflow_executor.py` runs user-controlled code with `exec(code, exec_globals)` inside the API process.

**Exploit path:** A workflow with a Code Runner node can walk Python's class hierarchy, recover module globals such as `sys`/`os`, and execute shell commands or read process environment secrets.

**Remediation:** Disable Code Runner by default in production and replace in-process execution with an isolated, killable sandbox such as a locked-down subprocess/container, gVisor, Firecracker, or WASM runtime.

## P0: Add SSRF Protection for Workflow HTTP and KYC Requests

**Impact:** Workflow authors can make the backend request arbitrary URLs, including loopback, private network services, Docker service names, and cloud metadata endpoints.

**Evidence:** `backend/app/services/workflow_executor.py` executes HTTP node URLs and custom KYC endpoints directly with `httpx.AsyncClient` without scheme, host, DNS, redirect, or private-IP validation.

**Exploit path:** A workflow can call `http://127.0.0.1:8000`, `http://postgres:5432`, `http://redis:6379`, or `http://169.254.169.254` from the backend network context.

**Remediation:** Centralize outbound URL validation, restrict schemes, block private/loopback/link-local/multicast/reserved ranges, validate DNS results before connect, disable or validate redirects, and consider per-tenant/domain allowlists.

## P0: Enforce Credits Before Execution and Make Billing Atomic

**Impact:** Users with zero or negative balance can run expensive workflows and consume platform LLM/KYC resources before credits are charged.

**Evidence:** `backend/app/api/workflows.py` calls `workflow_executor.execute_workflow(...)` first, then `_charge_credits(...)` increments `credits_used` afterward without an atomic cap.

**Exploit path:** A user can trigger many concurrent expensive workflows while below or near the credit limit; each request runs before billing catches up.

**Remediation:** Estimate/reserve credits before execution, reject insufficient balances, and settle actual usage with an atomic database update or row lock.

## P0: Stop Storing and Returning Raw Secrets

**Impact:** Database readers, backups, admins, logs, or compromised accounts can recover provider keys, node auth tokens, and static API tokens.

**Evidence:** Provider keys are plaintext columns in `backend/app/models/user.py`; workflow node secrets are saved in `backend/app/models/workflow.py` `graph_data`; full API tokens are returned by `backend/app/schemas/user.py` and `backend/app/api/admin.py`.

**Exploit path:** Reading workflow JSON or user/admin API responses exposes bearer tokens, KYC keys, custom headers, and long-lived API tokens.

**Remediation:** Store secret references instead of raw graph values, encrypt provider credentials with a managed key, hash API tokens at rest, and return full tokens only once at creation/rotation.

## P1: Redact Execution Traces, KYC Responses, Model Outputs, and Logs

**Impact:** PII, KYC provider responses, LLM prompts/outputs, document data, and downstream API responses are persisted and exposed through execution APIs and logs.

**Evidence:** `backend/app/models/workflow.py` stores `input_data`, `output_data`, and `execution_trace`; `backend/app/schemas/workflow.py` returns full traces; KYC returns `raw_response`; LLM outputs are logged at INFO level.

**Exploit path:** Any workflow owner or admin with execution read access can retrieve sensitive raw payloads. Log aggregation may store sensitive data indefinitely.

**Remediation:** Redact sensitive fields before persistence/response, remove raw KYC responses from normal outputs, truncate/sanitize logs, and add a retention policy for execution data.

## P1: Release DB Sessions Before Long Workflow Execution

**Impact:** Request-scoped database sessions remain open during long LLM/HTTP workflow execution, increasing connection pool starvation risk under concurrency.

**Evidence:** `backend/app/api/workflows.py` receives `db: Session = Depends(get_db)` and awaits `workflow_executor.execute_workflow(...)` before the dependency closes the session.

**Exploit path:** Multiple long-running executions keep DB sessions checked out while waiting on external services, causing unrelated API requests to hang.

**Remediation:** Fetch workflow/config data, commit and close the session, run workflow execution outside the DB session, then open a fresh session for completion and billing. Longer term, move execution to a background queue.

## P1: Fix Auth Token and Inactive Account Handling

**Impact:** Inactive users receive misleading generic errors, JWT expiry configuration is ignored, and brute-force/API abuse lacks rate limits.

**Evidence:** `backend/app/core/auth.py` filters inactive users during token lookup and returns `401 Invalid or expired token`; `create_access_token` hardcodes 30 days; docs state no rate limits.

**Exploit path:** Users cannot distinguish pending activation from invalid credentials. Stolen tokens remain valid for longer than configured. Attackers can brute-force login or spam workflow triggers.

**Remediation:** Look up users by valid token first, return `403` for inactive accounts, honor `ACCESS_TOKEN_EXPIRE_MINUTES`, add login/trigger rate limits, and define API token expiry/rotation policy.

## P1: Fix Verification and Decision Routing Logic

**Impact:** Workflows that use AI verification or decision nodes as gates can route incorrectly and approve unsafe or invalid data.

**Evidence:** `backend/app/services/workflow_executor.py` hardcodes verification results to `"pass"` and decision JSON parse fallback approves any malformed model output containing `approved`.

**Exploit path:** A model response that says “not approved” or includes the word “approved” in an explanation can route to the approved branch after JSON parse failure.

**Remediation:** Parse structured pass/fail output, fail closed on malformed model responses, validate decision labels against allowed handles, and add tests for malformed/ambiguous outputs.
