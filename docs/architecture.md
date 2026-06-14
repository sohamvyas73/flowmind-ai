# Architecture

This document describes how FlowMind AI is structured — the components, how they interact, the database schema, and the data flow from a browser click to an AI response.

---

## System Overview

```
┌──────────────────────────────────────────────────┐
│                   Browser                         │
│                                                   │
│  ┌──────────────┐    ┌─────────────────────────┐ │
│  │  Node Palette│    │    WorkflowCanvas         │ │
│  │  (sidebar)   │───▶│    (React Flow)          │ │
│  └──────────────┘    └───────────┬─────────────┘ │
│                                  │ Zustand store  │
│  ┌───────────────────────────────▼─────────────┐ │
│  │             NodePropertiesPanel              │ │
│  │             ExecutionModal                   │ │
│  │             Toolbar (Save/Load/Execute)      │ │
│  └───────────────────────────────┬─────────────┘ │
└──────────────────────────────────┼────────────────┘
                                   │ axios / HTTP
                    ┌──────────────▼──────────────┐
                    │       FastAPI Backend         │
                    │                              │
                    │  POST /workflows             │
                    │  GET  /workflows             │
                    │  PUT  /workflows/{id}        │
                    │  DELETE /workflows/{id}      │
                    │  POST /workflows/{id}/execute│
                    │  POST /workflows/{id}/trigger│
                    └───────────┬──────────────────┘
                                │
              ┌─────────────────┼────────────────────┐
              │                 │                    │
    ┌─────────▼──────┐  ┌──────▼──────┐  ┌─────────▼──────┐
    │   PostgreSQL    │  │    Redis     │  │  Google Gemini  │
    │  (workflows +   │  │  (future     │  │  via LangChain  │
    │   executions)   │  │   queuing)   │  │  (AI nodes)     │
    └────────────────┘  └─────────────┘  └────────────────┘
```

---

## Component Map

### Frontend

| File | Role |
|---|---|
| `WorkflowCanvas.tsx` | Mounts React Flow. Registers all 14 node types. Handles drag-drop from palette onto canvas, node selection, and edge connections. Passes Zustand state to React Flow. |
| `NodePalette.tsx` | Left sidebar. Lists all 14 draggable node types. Shows sample workflow cards. Pings `/health` every 5s for backend status indicator. |
| `NodePropertiesPanel.tsx` | Right sidebar. Shows config form for the currently selected node. All changes call `updateNodeData()` in Zustand which updates `nodes[]` in real time. |
| `CustomNodes.tsx` | 14 `memo`'d React components, one per node type. Each reads `data` from Zustand and renders a colored card with relevant badges. Routing nodes have multiple source Handles. |
| `ExecutionModal.tsx` | Two-phase dialog: (1) collects input field values (text/file/JSON), (2) runs the workflow and renders the per-step trace using `StepSummary` subcomponents. |
| `Toolbar.tsx` | Top-center buttons: Save (POST or PUT), Load (opens `LoadWorkflowModal`), Execute (opens `ExecutionModal`), Live API (opens `LiveApiPanel`). |
| `workflowStore.ts` | Zustand store. Single source of truth for `nodes`, `edges`, `selectedNode`, `workflowId`, and `workflowName`. `updateNodeData()` updates both `nodes[]` and `selectedNode` atomically to prevent stale reads. |
| `api.ts` | Thin Axios wrapper. All backend calls go through here. Base URL is `http://localhost:8000/api/v1`. |

### Backend

| File | Role |
|---|---|
| `main.py` | FastAPI app setup. Registers CORS middleware, mounts the workflows router, creates database tables on startup. |
| `api/workflows.py` | REST endpoint handlers. Thin layer: validate input, delegate to `WorkflowExecutor`, write result to DB, return response. |
| `services/workflow_executor.py` | The core. `NodeExecutor` contains all 14 node execution methods. `WorkflowExecutor` orchestrates them using the routing-aware execution engine. ~1200 lines. |
| `models/workflow.py` | SQLAlchemy ORM. Two tables: `workflows` and `workflow_executions`. JSON columns store graph data and execution traces. |
| `schemas/workflow.py` | Pydantic v2 request/response models. Used by FastAPI for automatic validation and serialization. |
| `core/config.py` | Reads `.env` via `pydantic-settings`. All config is accessed via `settings.*`. |
| `core/database.py` | SQLAlchemy `engine` and `SessionLocal`. `get_db()` is a FastAPI dependency that yields a session and closes it after the request. |

---

## Database Schema

### `workflows` table

```sql
CREATE TABLE workflows (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR NOT NULL,
    description TEXT,
    graph_data  JSONB NOT NULL,          -- { nodes: [...], edges: [...] }
    status      VARCHAR DEFAULT 'draft', -- draft | active | paused | archived
    version     VARCHAR DEFAULT '1.0',
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);
```

The `graph_data` column stores the entire React Flow graph as JSON. Node `data` objects (with all configuration like `rules`, `cases`, `code`, etc.) are nested inside.

### `workflow_executions` table

```sql
CREATE TABLE workflow_executions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id     UUID REFERENCES workflows(id),
    status          VARCHAR,              -- pending | running | completed | failed
    input_data      JSONB,               -- what was passed to /execute or /trigger
    output_data     JSONB,               -- final node's result
    execution_trace JSONB,               -- array of per-node { node_id, node_type, result }
    error_message   TEXT,
    started_at      TIMESTAMP DEFAULT NOW(),
    completed_at    TIMESTAMP
);
```

---

## Request Lifecycle: Execute

```
Browser clicks "Run Workflow"
  │
  ▼
ExecutionModal collects field inputs (text/file/JSON)
  │
  ▼
POST /api/v1/workflows/{id}/execute
  { input_data: { node_inputs: { "node_abc": { "customer_id": { content: "123" } } } } }
  │
  ▼
FastAPI handler (api/workflows.py)
  ├── Fetch workflow from DB
  ├── Create WorkflowExecution record (status=RUNNING)
  └── Call workflow_executor.execute_workflow(graph_data, input_data)
        │
        ▼
        WorkflowExecutor.execute_workflow()
          ├── Build incoming edge index per node
          ├── Find root nodes (no incoming edges)
          └── While ready queue not empty:
                ├── Pop next node
                ├── Build context { input, previous_output, current_node_id }
                ├── Call NodeExecutor._execute_node(type, data, context)
                │     └── Dispatches to execute_ai_node / execute_rule_node / etc.
                ├── Check result for { error } → halt and return failed status
                ├── Check result for { status: "awaiting_review" } → halt and return paused
                ├── Read result._active_handles → determine which outgoing edges fire
                └── Enqueue downstream nodes whose all incoming edges have fired
        │
        ▼
  Update WorkflowExecution (status=COMPLETED/FAILED, output_data, execution_trace)
  │
  ▼
Return ExecutionResponse to browser
  │
  ▼
ExecutionModal renders step-by-step trace
```

---

## Request Lifecycle: Trigger

The `/trigger` endpoint is for external systems calling the workflow as a webhook/API:

```
External system
  │
  POST /api/v1/workflows/{id}/trigger
  { "customer_id": "123", "amount": 4999.00 }
  │
  ▼
Same execution flow as above, BUT input is not nested under node_inputs.
Input node detects this and maps top-level keys directly to fields by name.
  │
  ▼
Returns TriggerResponse:
  { workflow_id, execution_id, status, output }
```

---

## Data Flow Between Nodes

Each node receives a `context` dict:

```python
context = {
    "input":           raw_input_data,   # original payload from the request
    "previous_output": {},                # result of the immediately previous node
    "current_node_id": "node_xyz",
}
```

Each node returns a result dict that becomes `previous_output` for the next node. Node types that route (Decision, Rule Engine, Switch) include `_active_handles: ["approved"]` in their result — the orchestrator uses this to decide which outgoing edges activate.

### Output structure by node type

| Node | Key fields in result |
|---|---|
| Input | `inputs: {field: value}`, `filenames: {field: filename}` |
| AI Agent | `result: <text or parsed JSON>`, `task`, `format`, `confidence` |
| Verification | `result: "pass"`, `confidence`, `analysis` |
| Decision | `decision`, `confidence`, `threshold`, `reasoning`, `key_findings`, `_active_handles` |
| Output | `output_type`, `data`, `status` |
| HTTP | `status_code`, `success`, `response`, `url`, `method` |
| Transform | `transformed: {key: value}`, `mode` |
| Human Review | `status: "awaiting_review"`, `review_prompt`, `data_to_review` |
| Rule Engine | `passed`, `matched_rules`, `failed_rules`, `_active_handles` |
| Code Runner | `output: <any>`, `executed: true` |
| Validator | `passed`, `errors: []` or `error: "..."` (fails workflow) |
| Switch | `routed_to`, `switch_value`, `_active_handles` |
| Formatter | `rendered`, `subject`, `format` |
| Aggregator | `result`, `operation`, `item_count` |

---

## Template Substitution

Nodes that support `{{variable}}` syntax (HTTP, Transform template, Formatter, Switch) use `_substitute_template()`:

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

Before substitution, `_flatten_previous()` extracts a flat key-value dict from the previous node's output structure, handling all the different result shapes (inputs/transformed/response/direct).

---

## Logging Strategy

Every node logs at two points:
1. **Before the operation** — node ID, type, configuration, and sanitized input
2. **After the operation** — result (sanitized), elapsed time

For AI nodes, full model input and full model output are logged at `INFO` level — not truncated. Base64 file data is replaced with `[file: image/jpeg, ~42 KB]` to keep logs readable.

Log format: `YYYY-MM-DD HH:MM:SS [INFO] app.services.workflow_executor: [node_type] node=<id> | ...`

---

## Security Considerations

**Code Runner sandboxing:** The `exec()` call runs with a restricted `__builtins__` dict — `__import__` is excluded, so `import os`, `import subprocess`, and similar calls are blocked at the Python level. An `asyncio.wait_for` timeout prevents infinite loops. This is not a production-grade sandbox (a proper sandbox requires a subprocess or container boundary), but it prevents casual misuse.

**API keys:** Stored in `.env`, read via `pydantic-settings`, never logged, never sent to the frontend.

**File uploads:** File contents are passed as base64 data URIs within the JSON payload. The `_strip_binaries()` function replaces them before passing to downstream nodes to prevent flooding the LLM context.

**SQL injection:** SQLAlchemy ORM with parameterized queries throughout. No raw SQL.

---

## Frontend State Management

Zustand is used instead of Redux or React Context because the store is small and mutations are always synchronous (except the async `onRun` handler in ExecutionModal). The key invariant is that `updateNodeData()` updates both `nodes[]` and `selectedNode` in a single `set()` call to prevent the properties panel from reading stale data after an edit.

```typescript
updateNodeData: (nodeId, data) => {
    const updatedNodes = get().nodes.map(node =>
        node.id === nodeId ? { ...node, data: { ...node.data, ...data } } : node
    );
    const sel = get().selectedNode;
    set({
        nodes: updatedNodes,
        selectedNode: sel?.id === nodeId
            ? (updatedNodes.find(n => n.id === nodeId) ?? sel)
            : sel,
    });
},
```
