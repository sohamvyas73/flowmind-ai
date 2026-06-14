# FlowMind AI — Visual AI Workflow Builder

**Build, run, and automate AI-powered pipelines using a drag-and-drop canvas. No code required.**

FlowMind AI is an open-source platform for creating multi-step AI workflows visually. Connect nodes on a canvas, configure them through a properties panel, and execute the workflow via the built-in UI or a REST API trigger — all backed by Google Gemini, FastAPI, and PostgreSQL.

---

## What It Does

You drag nodes onto a canvas, connect them with edges, and each connection tells the system how data flows. When you run a workflow:

1. Input data enters through an **Input node** (from the UI or a webhook)
2. It passes through any combination of AI nodes, rule engines, validators, HTTP calls, transformers, and more
3. Conditional routing nodes send data down different branches based on results
4. It exits through an **Output node** — as an API response, notification, database write, or webhook

Every step is logged with full model inputs/outputs so you can debug exactly what happened.

---

## Screenshots

**Node library and empty canvas**
![Node library and empty canvas](screenshots/01-canvas-empty.png)

**Loan Eligibility workflow** — Input → Validator → Rule Engine → AI Analysis → Decision → Formatter → Output, with conditional branching
![Loan Eligibility workflow](screenshots/02-loan-eligibility-workflow.png)

**Rule Engine properties panel** — AND/OR conditions with 18 operators, no LLM
![Rule Engine properties](screenshots/03-rule-engine-properties.png)

**Fraud Detection workflow** — dual AI nodes feeding a Decision node with approve/reject routing
![Fraud Detection workflow](screenshots/07-fraud-detection-workflow.png)

**AI Agent properties panel** — task type, output format, temperature slider, custom prompt
![AI Agent properties](screenshots/05-ai-node-properties.png)

**Validator node properties** — field-level schema rules with type, required, min/max, enum
![Validator properties](screenshots/08-validator-properties.png)

**Execute modal** — input fields collected per-node before running, with file upload support
![Execute modal](screenshots/06-execute-modal.png)

---

## Key Features

- **14 built-in node types** covering AI, HTTP, rules, code, validation, routing, formatting, and aggregation
- **Visual canvas** — drag, drop, connect, and configure entirely in the browser (React Flow)
- **Routing-aware execution engine** — conditional branches only fire when active; a Decision node's "rejected" branch never runs if the result is "approved"
- **Live API trigger** — every saved workflow gets a `/trigger` endpoint callable from any system
- **Full execution trace** — every node's prompt, model output, and result is logged and displayed
- **AI output formats** — text, JSON, CSV, HTML, Markdown, table, bullet list, or a custom JSON schema you define
- **Sandboxed Python execution** — run arbitrary Python snippets with an allowlisted stdlib and configurable timeout
- **Human-in-the-loop** — pause a workflow mid-execution for manual review before continuing
- **Docker Compose** — the entire stack starts with one command

---

## Node Types

| Node | Color | Purpose |
|---|---|---|
| Input | Blue | API trigger — defines the fields the workflow accepts |
| AI Agent | Purple | LLM call (Gemini) with task type, temperature, output format |
| Verification | Green | AI-powered consistency, compliance, or PII checks |
| Decision | Yellow | AI-powered approve/reject with confidence threshold |
| Output | Indigo | Deliver results (API, DB write, webhook, Slack, email) |
| HTTP Request | Orange | Call any external API with auth, headers, body templates |
| Transform | Teal | Rename/filter/reshape data without an LLM |
| Human Review | Rose | Pause execution for manual approval |
| Rule Engine | Amber | AND/OR business rules with 18 operators — no LLM |
| Code Runner | Zinc | Sandboxed Python with json, re, math, datetime |
| Validator | Emerald | Field-level schema validation — halts workflow on failure |
| Switch Router | Violet | Route to N branches by field value (supports OR via `|`) |
| Formatter | Lime | Template-based output rendering (text, HTML, Markdown, email) |
| Aggregator | Sky | sum, avg, count, group_by, join, unique over arrays |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, React Flow, Zustand, Tailwind CSS, Vite |
| Backend | FastAPI, Python 3.11, SQLAlchemy 2, Pydantic v2, asyncio |
| AI | LangChain + Google Gemini (`gemini-1.5-flash` default) |
| Database | PostgreSQL 15 |
| Cache/Queue | Redis 7 |
| HTTP client | httpx (async) |
| Containers | Docker + Docker Compose |

---

## Quick Start

### Prerequisites

- Docker and Docker Compose installed
- A [Google AI Studio](https://aistudio.google.com/) API key (free tier works)

### 1. Clone

```bash
git clone https://github.com/your-org/flowmind-ai.git
cd flowmind-ai
```

### 2. Configure environment

```bash
cp backend/.env.example backend/.env
```

Open `backend/.env` and set your Gemini API key:

```env
GEMINI_API_KEY="your-key-here"
GEMINI_MODEL="gemini-1.5-flash"
```

### 3. Start the backend stack

```bash
docker compose up --build
```

This starts PostgreSQL on `5432`, Redis on `6379`, and the FastAPI backend on `http://localhost:8000`.

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

### 5. Build your first workflow

1. Drag an **Input** node onto the canvas
2. Drag an **AI Agent** node and connect them
3. Drag an **Output** node and connect it
4. Click **Save**, then **Execute**

---

## Running Without Docker

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # fill in your values
uvicorn app.main:app --reload --port 8000
```

You need a running PostgreSQL instance. Point `DATABASE_URL` in `.env` at it.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

---

## Project Structure

```
flowmind-ai/
├── backend/
│   ├── app/
│   │   ├── api/workflows.py          # REST endpoints (CRUD + execute + trigger)
│   │   ├── core/
│   │   │   ├── config.py             # Settings loaded from .env
│   │   │   └── database.py           # SQLAlchemy engine + session factory
│   │   ├── models/workflow.py        # ORM models (Workflow, WorkflowExecution)
│   │   ├── schemas/workflow.py       # Pydantic v2 request/response schemas
│   │   ├── services/
│   │   │   └── workflow_executor.py  # All node logic + routing engine
│   │   └── main.py                   # FastAPI app, CORS, router setup
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── CustomNodes.tsx        # 14 visual node components (memo'd)
│       │   ├── NodePalette.tsx        # Left sidebar — draggable node library
│       │   ├── NodePropertiesPanel.tsx # Right sidebar — node config form
│       │   ├── WorkflowCanvas.tsx     # React Flow canvas wrapper
│       │   ├── ExecutionModal.tsx     # Run dialog + step trace viewer
│       │   ├── LoadWorkflowModal.tsx  # Load/delete saved workflows
│       │   ├── LiveApiPanel.tsx       # Shows /trigger URL and curl example
│       │   └── Toolbar.tsx            # Save / Load / Execute / API buttons
│       ├── data/sampleWorkflows.ts    # 5 pre-built example workflows
│       ├── services/api.ts            # Axios client for backend calls
│       ├── store/workflowStore.ts     # Zustand global state
│       └── types/workflow.ts          # TypeScript interfaces
├── docker-compose.yml
└── docs/
    ├── architecture.md
    ├── nodes.md
    ├── use-cases.md
    ├── execution-engine.md
    └── api-reference.md
```

---

## API Quick Reference

Every saved workflow gets two endpoints:

```
POST /api/v1/workflows/{id}/execute    # Run from the UI
POST /api/v1/workflows/{id}/trigger    # Run from any external system
```

**Trigger example:**

```bash
curl -X POST http://localhost:8000/api/v1/workflows/{workflow_id}/trigger \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "cust_123", "amount": 4999.00}'
```

**Response:**

```json
{
  "workflow_id": "...",
  "execution_id": "...",
  "status": "completed",
  "output": { "decision": "approved", "confidence": 0.91 }
}
```

Full API docs: [docs/api-reference.md](docs/api-reference.md)

---

## Docs

| Document | What it covers |
|---|---|
| [Architecture](docs/architecture.md) | System design, data flow, component map, database schema |
| [Node Reference](docs/nodes.md) | Every node type — config fields, input/output schema, examples |
| [Use Cases](docs/use-cases.md) | KYC, fraud, loan eligibility, document processing, data pipelines |
| [Execution Engine](docs/execution-engine.md) | How conditional routing works internally |
| [API Reference](docs/api-reference.md) | All REST endpoints with request/response bodies |

---

## Sample Workflows

Five workflows are included and loadable from the Node Palette sidebar:

| Name | Nodes used |
|---|---|
| **KYC Verification** | Input → AI Extraction → Verification → Decision → Output |
| **Fraud Detection** | Input → AI Pattern Analysis → AI Fraud Score → Decision → Output |
| **Document Processing** | Input → AI OCR → AI Classification → Verification → Output |
| **API Enrichment + Review** | Input → HTTP → Transform → AI → Human Review → Output |
| **Loan Eligibility** | Input → Validator → Rule Engine → AI → Decision → Formatter → Output |

---

## Changing the AI Model

Edit `backend/.env`:

```env
GEMINI_MODEL="gemini-1.5-flash"    # faster, cheaper (default)
GEMINI_MODEL="gemini-1.5-pro"      # more capable, slower
```

Then: `docker compose restart backend`. No code changes needed.

---

## Roadmap

The current release covers the core canvas, 14 node types, and the execution engine. Below are the planned improvement phases, ordered by priority.

---

### Phase 2 — RAG & Memory

The most impactful missing capability: nodes that can retrieve context from a knowledge base before making an LLM call, and nodes that remember state across workflow runs.

| Node | Description |
|---|---|
| **RAG Retriever** | Connect to a vector database (Pinecone, Weaviate, ChromaDB, pgvector). Embed a query from the previous node's output, retrieve top-K relevant chunks, inject them into the next AI node's context automatically. |
| **Document Embedder** | Chunk a document (PDF, TXT, HTML) into segments, generate embeddings via Gemini or OpenAI, and upsert into a configured vector store. Use before a RAG Retriever to build the knowledge base. |
| **Memory Node** | Read/write key-value state that persists across workflow executions. Lets AI nodes access conversation history, user profiles, or running totals from previous runs — not just the current execution. |
| **Semantic Search** | Given a query, return the N most semantically similar items from a stored collection, ranked by cosine similarity. No full vector DB required — works against a JSON field in PostgreSQL using pgvector. |

**Why RAG matters here:** Right now every AI node only sees the current execution context. With a RAG Retriever node between an Input and an AI Agent, you can answer questions against a company knowledge base, a product catalog, or a compliance document library — all without fine-tuning.

---

### Phase 3 — Multi-Model & Streaming

| Improvement | Description |
|---|---|
| **Multi-model support** | Add OpenAI GPT-4o, Anthropic Claude, Mistral, and Ollama (local models) as selectable providers per AI node. Each node picks its own model — use a cheap fast model for classification, a powerful one for reasoning. |
| **Streaming output** | Stream LLM tokens to the browser in real time via Server-Sent Events. Long AI nodes currently block until complete — streaming makes execution feel instant and lets users see the model thinking. |
| **Agent loop node** | A node that runs an LLM in a ReAct loop — the model can call tools (other nodes), observe results, and decide to continue or stop. Enables true autonomous agents, not just linear pipelines. |
| **Model fallback** | Configure a primary and fallback model per AI node. If the primary times out or rate-limits, the fallback fires automatically. |

---

### Phase 4 — Triggers & Integrations

Right now the only trigger is a manual HTTP POST. This phase makes workflows event-driven.

| Feature | Description |
|---|---|
| **Scheduled triggers** | Cron-based execution — run a workflow every hour, daily, or on a custom schedule. Useful for batch report generation, periodic data enrichment, and digest emails. |
| **Webhook triggers** | Register a workflow as a listener for external events — Stripe payments, GitHub push events, Slack messages, form submissions. No polling needed. |
| **Email trigger** | Inbound email parsing — forward emails to a workflow-specific address and the content (sender, subject, body, attachments) becomes the Input node's payload. |
| **Native integrations** | First-class send nodes for Slack (post message), SendGrid (send email), Twilio (send SMS), and Notion (create/update page) — beyond the current generic webhook Output node. |
| **Database node** | Execute a SQL SELECT or INSERT directly as a node. Connects to any PostgreSQL or MySQL database. Replaces the pattern of using an HTTP node to call a database-backed API. |

---

### Phase 5 — Production & Scale

| Feature | Description |
|---|---|
| **Async execution queue** | Move workflow execution off the FastAPI request thread into a Redis/Celery queue. Long-running workflows (multiple LLM calls, slow external APIs) no longer block the HTTP response. Poll or webhook for completion. |
| **Parallel node execution** | Execute independent branches simultaneously instead of sequentially. A workflow with three HTTP nodes feeding the same aggregator currently runs them one at a time — parallelism would cut latency by 3x. |
| **Retry & backoff** | Configure per-node retry count and backoff strategy. An LLM node that fails due to a rate limit retries automatically with exponential backoff before marking the execution as failed. |
| **Secrets manager** | Encrypted credential storage in the database instead of plaintext `.env` values. API keys, bearer tokens, and database passwords are stored encrypted and injected at runtime — never exposed in logs or the UI. |
| **Execution timeout** | Per-workflow maximum execution time. Workflows that run longer than the configured limit are cancelled and marked as failed — prevents runaway LLM loops from consuming quota indefinitely. |
| **Rate limiting** | Per-workflow and per-API-key request limits. Prevents a single workflow trigger flood from consuming the entire Gemini quota. |

---

### Phase 6 — Collaboration & Ecosystem

| Feature | Description |
|---|---|
| **Multi-tenant auth** | User accounts, organisations, and role-based access. Workflows belong to an organisation, not just a single user. Members can view, edit, or execute based on their role. |
| **Workflow versioning** | Every Save creates a version snapshot. Roll back to any previous version, diff two versions, and promote a version to "active" while keeping the draft in progress. |
| **Testing mode** | Dry-run a workflow with mock LLM responses — a configurable stub returns a fixed response for every AI node. Lets you test routing logic and validate node configurations without spending API quota. |
| **Workflow marketplace** | Import and export workflows as JSON. A community gallery of pre-built workflows (KYC, invoice processing, support routing, RAG Q&A, etc.) that can be loaded with one click and customised. |
| **Execution analytics** | Per-workflow dashboard: success rate, average latency, LLM token usage, cost estimate per execution, and error breakdown by node type. |
| **Sub-workflow node** | Call another saved workflow as a node inside the current one. Enables composing complex pipelines from smaller reusable pieces — the workflow equivalent of a function call. |

---

## Contributing

Contributions are welcome. The codebase is intentionally kept straightforward.

**Adding a new node type** requires touching 6 files:
1. `workflow_executor.py` — add `execute_<name>_node()` and register in `_execute_node()`
2. `CustomNodes.tsx` — add the visual component
3. `WorkflowCanvas.tsx` — register in `nodeTypes` and minimap colors
4. `workflowStore.ts` — add default data and label in `addNode()` / `getNodeLabel()`
5. `NodePropertiesPanel.tsx` — add the config form section
6. `types/workflow.ts` — add the type string to the `NodeType` union

Please read [docs/architecture.md](docs/architecture.md) before making structural changes.

Bug reports: open an issue and paste the execution trace JSON from the step that failed.

---

## License

MIT — see `LICENSE`.

---

## Origin

FlowMind AI was conceived and originally designed by **[Soham Vyas](https://github.com/sohamvyas73)**. The core idea — making AI pipeline automation as simple as connecting blocks on a canvas, without writing orchestration code — came from his work on AI-driven product workflows and the gap he saw between powerful LLM capabilities and the tooling available to non-ML engineers.

---

## Acknowledgements

- [React Flow](https://reactflow.dev/) — the canvas engine
- [LangChain](https://langchain.com/) — LLM abstraction layer
- [Google Gemini](https://ai.google.dev/) — the default AI model
- [FastAPI](https://fastapi.tiangolo.com/) — backend framework
