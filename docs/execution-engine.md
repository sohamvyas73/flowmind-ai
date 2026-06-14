# Execution Engine

How FlowMind AI executes workflows — the orchestration algorithm, conditional routing, error handling, and logging pipeline.

---

## The Core Problem

A naive approach to workflow execution would topologically sort all nodes and execute them in order. This fails for conditional branching: if a Decision node routes to "approved", the "rejected" branch should never run. The naive sort has no way to skip it.

FlowMind AI solves this with a **routing-aware dynamic execution engine** built around the `_active_handles` protocol.

---

## How the Engine Works

The engine is in `workflow_executor.py` → `WorkflowExecutor.execute_workflow()`.

### Step 1: Build the Graph Index

```python
# Index: for each node, which edges come INTO it
incoming: Dict[str, List[Dict]] = {n["id"]: [] for n in nodes}
for edge in edges:
    if edge["target"] in incoming:
        incoming[edge["target"]].append(edge)
```

### Step 2: Find Root Nodes

Nodes with no incoming edges are "roots" — they run first with no prerequisites.

```python
ready: List[str] = [n["id"] for n in nodes if not incoming[n["id"]]]
```

A typical workflow has one root: the Input node.

### Step 3: Dynamic Execution Loop

```python
fired_edges: set = set()    # tracks which edges have "activated"

while ready:
    node_id = ready.pop(0)
    
    # 1. Execute the node
    result = await _execute_node(node_type, node_data, context)
    
    # 2. Check which outgoing edges should fire
    active_handles = result.get("_active_handles")  # e.g. ["approved"]
    outgoing = [e for e in edges if e["source"] == node_id]
    
    if active_handles is not None:
        # Routing node: only fire edges whose sourceHandle is in active_handles
        active_out = [e for e in outgoing if e.get("sourceHandle") in active_handles]
    else:
        # Non-routing node: fire all outgoing edges
        active_out = outgoing
    
    # 3. Mark those edges as fired
    for edge in active_out:
        fired_edges.add(edge["id"])
    
    # 4. Enqueue downstream nodes that are now "ready"
    for edge in active_out:
        target = edge["target"]
        # A node is ready when ALL its incoming edges have fired
        if all(e["id"] in fired_edges for e in incoming.get(target, [])):
            ready.append(target)
```

### Why This Works

Consider this graph:

```
Decision
  ├── [approved] → Format Email → Send Email
  └── [rejected] → Log Rejection
```

When Decision runs and returns `_active_handles: ["approved"]`:

- The `approved` edge fires → it's added to `fired_edges`
- The `rejected` edge does NOT fire → never added to `fired_edges`
- "Format Email" is checked: all its incoming edges (just the approved edge) are in `fired_edges` → it gets enqueued
- "Log Rejection" is checked: its incoming edge (the rejected edge) is not in `fired_edges` → it never gets enqueued
- "Log Rejection" never executes

The `rejected` branch is skipped without any special-case logic — it just never gets added to the `ready` queue.

---

## The `_active_handles` Protocol

Three node types use this protocol:

### Decision Node

Returns `_active_handles: ["approved"]` or `_active_handles: ["rejected"]` depending on the LLM's verdict:

```python
return {
    "decision": decision,           # "approved" or "rejected"
    ...
    "_active_handles": [decision],  # ["approved"] or ["rejected"]
}
```

Connect the Decision node's source handles:
- `approved` handle → success branch
- `rejected` handle → failure branch

### Rule Engine Node

Returns `_active_handles: ["pass"]` or `_active_handles: ["fail"]`:

```python
route = "pass" if passed else "fail"
return {
    "passed": passed,
    ...
    "_active_handles": [route],
}
```

### Switch Router Node

Returns `_active_handles: ["case_0"]` (or whichever case matched):

```python
return {
    "routed_to": matched_handle,
    ...
    "_active_handles": [matched_handle],
}
```

The `default` handle fires when no case matches.

### Non-Routing Nodes

All other nodes (AI, HTTP, Transform, Validator, Code Runner, etc.) do NOT include `_active_handles` in their result. When `active_handles is None`, all outgoing edges fire. This is backward compatible — you can add a regular node anywhere without thinking about handles.

---

## Execution States

The engine produces one of three outcomes:

### Completed

All reachable nodes ran successfully. `final_output` is the result of the last node in the execution chain.

```python
{
    "status": "completed",
    "execution_trace": [...],
    "final_output": { ... },
    "timestamp": "..."
}
```

### Failed

A node returned `{"error": "..."}`. The engine halts immediately — no downstream nodes run.

```python
{
    "status": "failed",
    "failed_node_id": "node_abc",
    "failed_node_type": "validatorNode",
    "failed_node_label": "Field Validation",
    "error": "Validation failed (1 error): 'credit_score' (250) is below minimum 300",
    "execution_trace": [...],  # includes steps up to and including the failed node
    "final_output": None,
    "timestamp": "..."
}
```

Nodes that intentionally halt the workflow by returning errors:
- **Validator node** — when a field fails validation rules
- **HTTP node** — when the URL is empty or the request fails
- **Code Runner** — when code raises an unhandled exception or times out
- **Any node** — if the LLM call fails (API error, timeout)

### Paused

A Human Review node was reached. Execution stops and the review data is returned. The workflow execution is stored in the database with status `COMPLETED` so it can be queried.

```python
{
    "status": "paused",
    "paused_node_id": "node_xyz",
    "paused_node_label": "Analyst Review",
    "review_data": {
        "status": "awaiting_review",
        "review_prompt": "...",
        "data_to_review": { ... }
    },
    "execution_trace": [...],
    "timestamp": "..."
}
```

---

## The Execution Trace

Every node appends an entry to `execution_trace` as it runs:

```json
[
  {
    "node_id": "node_001",
    "node_type": "inputNode",
    "result": { "inputs": { "customer_id": "cust_123" }, "timestamp": "..." },
    "timestamp": "2025-01-15T10:30:00Z"
  },
  {
    "node_id": "node_002",
    "node_type": "aiNode",
    "result": { "task": "extraction", "result": "...", "confidence": 0.85 },
    "timestamp": "2025-01-15T10:30:01Z"
  },
  ...
]
```

The trace is stored in `workflow_executions.execution_trace` (JSONB) and returned to the browser, which renders it step-by-step in the ExecutionModal.

---

## Context Passing

Each node receives a `context` dict:

```python
context = {
    "input":           raw_input_data,      # original request payload
    "previous_output": {},                   # output of the previous node
    "current_node_id": "node_abc",
}
```

After each node runs successfully, `context["previous_output"]` is updated:

```python
context["previous_output"] = result
```

This means each node sees only the **immediately previous** node's output. There is no global state accumulation. If you need values from an earlier node, use a Transform node to reshape the data and carry forward the fields you need.

---

## Template Substitution

Before HTTP, Transform (template mode), Formatter, and Switch nodes execute, they call `_substitute_template()` to replace `{{field}}` placeholders in their configuration with live values from the previous node's output.

```python
@staticmethod
def _substitute_template(template: str, data: Dict[str, Any]) -> str:
    def replace_match(m):
        key = m.group(1).strip()
        val = data
        for part in key.split('.'):
            val = val.get(part) if isinstance(val, dict) else None
        return str(val) if val is not None else ''
    return re.sub(r'\{\{([^}]+)\}\}', replace_match, template)
```

Before template substitution, `_flatten_previous()` extracts a consistent flat dict from the previous node's output regardless of its structure:

```python
@staticmethod
def _flatten_previous(previous_output: Any) -> Dict[str, Any]:
    if not isinstance(previous_output, dict):
        return {}
    if "inputs" in previous_output:       # Input node output
        return previous_output["inputs"]
    if "transformed" in previous_output:  # Transform node output
        t = previous_output["transformed"]
        return t if isinstance(t, dict) else previous_output
    if "response" in previous_output:     # HTTP node output
        r = previous_output["response"]
        return r if isinstance(r, dict) else previous_output
    return previous_output                # Everything else: use as-is
```

---

## Logging Pipeline

All logging is done through Python's standard `logging` module at `INFO` level. The format is:

```
2025-01-15 10:30:01 [INFO] app.services.workflow_executor: [ai_node] node=node_002 | task=extraction | format=json | prompt='Extract name...'
2025-01-15 10:30:01 [INFO] app.services.workflow_executor: [ai_node] node=node_002 | MODEL INPUT ↓
{...sanitized message list...}
2025-01-15 10:30:02 [INFO] app.services.workflow_executor: [ai_node] node=node_002 | MODEL OUTPUT ↓ (1.24s)
The extracted name is John Smith, DOB...
```

### Log Sanitization

Two sanitization functions prevent sensitive or bulky data from flooding logs:

**`_safe_result()`** — used for node result summaries in workflow orchestration logs. Truncates strings over 200 chars; replaces base64 data URIs with `[file: mime/type, ~N KB]`.

**`_safe_messages()`** — used when logging the message list sent to the LLM. Sanitizes image_url and media content parts while preserving text parts.

**Full AI output is NOT truncated** — the complete model response is logged at `INFO` level. This is intentional: you need to see the full LLM output to debug issues.

### Workflow-Level Log Markers

```
=== WORKFLOW START | nodes=5 edges=4 roots=['node_001'] ===
--- NODE START | id=node_001 type=inputNode label='Customer Data' ---
--- NODE END   | id=node_001 type=inputNode label='Customer Data' | OK 0.01s | result=... ---
...
=== WORKFLOW END | 3.42s | executed=4/5 nodes ===
```

(4/5 nodes because the rejected branch was skipped)

---

## LLM Initialization

The LLM client is created fresh on every AI node call:

```python
def _get_llm(self, temperature: float = 0.0) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        google_api_key=settings.GEMINI_API_KEY,
        model=settings.GEMINI_MODEL,
        temperature=temperature,
        convert_system_message_to_human=True,
    )
```

This means changing `GEMINI_MODEL` or `GEMINI_API_KEY` in `.env` and restarting the backend takes effect immediately — no code change, no cache invalidation.

`convert_system_message_to_human=True` is required because the Gemini API does not support the `system` role natively; LangChain converts it by prepending the system message to the first human turn.

---

## Running Node Execution

All LLM calls and the Code Runner use `asyncio.to_thread()` to avoid blocking the FastAPI event loop:

```python
response = await asyncio.to_thread(llm.invoke, messages)
```

The Code Runner also wraps this in `asyncio.wait_for()` for timeout enforcement:

```python
output_val = await asyncio.wait_for(
    asyncio.to_thread(_run),
    timeout=timeout_s
)
```

HTTP requests use `httpx.AsyncClient` which is natively async and doesn't need `to_thread`.

---

## Database Write Lifecycle

1. **Before execution:** A `WorkflowExecution` record is created with `status=RUNNING`
2. **After execution:** The record is updated with `status=COMPLETED/FAILED`, `output_data`, `execution_trace`, and `completed_at`
3. **On exception:** The record is updated with `status=FAILED` and `error_message`

The execution record is always written, even if the workflow fails — so you can always query what happened.

```python
# Simplified from api/workflows.py
execution = WorkflowExecution(status=RUNNING, input_data=...)
db.add(execution); db.commit()

try:
    result = await workflow_executor.execute_workflow(...)
    execution.status = COMPLETED
    execution.output_data = result["final_output"]
    execution.execution_trace = result["execution_trace"]
except Exception as e:
    execution.status = FAILED
    execution.error_message = str(e)
finally:
    execution.completed_at = datetime.utcnow()
    db.commit()
```
