# Use Cases

Real-world scenarios and how to build them in FlowMind AI. Each section covers what the use case is, the workflow design, which nodes to use and why, and the expected execution flow.

---

## Table of Contents

1. [KYC / Identity Verification](#1-kyc--identity-verification)
2. [Fraud Detection](#2-fraud-detection)
3. [Loan Eligibility Assessment](#3-loan-eligibility-assessment)
4. [Document Processing Pipeline](#4-document-processing-pipeline)
5. [API Data Enrichment with Human Review](#5-api-data-enrichment-with-human-review)
6. [Customer Support Ticket Routing](#6-customer-support-ticket-routing)
7. [Invoice Processing and Validation](#7-invoice-processing-and-validation)
8. [Batch Data Aggregation Report](#8-batch-data-aggregation-report)
9. [Content Moderation Pipeline](#9-content-moderation-pipeline)
10. [Multi-language Document Translation](#10-multi-language-document-translation)

---

## 1. KYC / Identity Verification

**Domain:** Fintech, Banking, Insurance  
**Trigger:** New customer onboarding or account opening  
**Goal:** Verify that a customer's identity document is valid, extract their details, and make a compliance decision

### Workflow

```
Input (customer_id, full_name, identity_document[file])
  │
  ▼
AI Agent [extraction, temperature=0.2]
  "Extract name, DOB, document number, expiry date, and issuing country from the identity document."
  │
  ▼
Verification [compliance]
  "Cross-verify that extracted fields match the submitted name and meet document requirements."
  │
  ▼
Decision [threshold=0.85]
  "Approve only if document is valid, not expired, and all required fields are present and consistent."
  ├── approved → Output [database] "Save verified customer"
  └── rejected → Output [notification] "Flag for manual review"
```

### Why This Works

- The AI Agent with `extraction` task and low temperature gives consistent, structured output
- `compliance` verification cross-checks extracted data against the submitted name
- The Decision node threshold of 0.85 means the model must be highly confident before approving

### Input Schema

```json
{
  "customer_id": "cust_001",
  "full_name": "Sarah Connor",
  "identity_document": "<base64-encoded PDF or image>"
}
```

### Expected Output (approved path)

```json
{
  "decision": "approved",
  "confidence": 0.92,
  "key_findings": [
    "Document type: Passport",
    "Name matches: Sarah Connor",
    "Expiry: 2029-08-15 (valid)",
    "Document number: L898902C"
  ]
}
```

---

## 2. Fraud Detection

**Domain:** Payments, E-commerce, Banking  
**Trigger:** Incoming transaction or payment event  
**Goal:** Score a transaction for fraud risk and alert if high risk

### Workflow

```
Input (transaction_id, amount, transaction_data[json])
  │
  ▼
AI Agent [reasoning, outputFormat=json, temperature=0.3]
  "Analyze transaction patterns. Look for anomalies: unusual amount, time, location, velocity."
  │
  ▼
AI Agent [fraud_detection, outputFormat=json, temperature=0.2]
  "Calculate fraud probability (0.0–1.0) based on detected patterns. Return score and flags."
  │
  ▼
Rule Engine [AND]
  Rule 1: fraud_score gte 0.7  (label: "High fraud score")
  ├── pass → Output [notification] "FRAUD ALERT: Block transaction"
  └── fail → Output [api] "Transaction approved"
```

### Alternative: Use Decision Node Instead of Rule Engine

If you want the AI to make the final call rather than a hard threshold:

```
... → AI Fraud Score → Decision [threshold=0.7] → (approved) Output | (rejected) Alert
```

Use Rule Engine when the threshold is fixed and non-negotiable. Use Decision when you want the AI to weigh context.

### Input Schema

```json
{
  "transaction_id": "txn_8821",
  "amount": 9999.99,
  "transaction_data": {
    "merchant": "Unknown Merchant LLC",
    "location": "Lagos, Nigeria",
    "user_location": "New York, USA",
    "velocity_last_hour": 5
  }
}
```

---

## 3. Loan Eligibility Assessment

**Domain:** Lending, Credit, Banking  
**Trigger:** Loan application submission  
**Goal:** Validate application data, check hard eligibility rules, run AI risk analysis, make a decision, and send an approval or rejection notification

### Workflow (the built-in sample)

```
Input (applicant_name, annual_income, credit_score, loan_amount, employment_status)
  │
  ▼
Validator
  - annual_income: required, number, min=1000
  - credit_score: required, number, min=300, max=850
  - loan_amount: required, number, min=1000
  - employment_status: required, enum=employed|self-employed|retired
  │  (fails here → workflow halts with validation error)
  ▼
Rule Engine [AND]
  Rule 1: credit_score gte 650
  Rule 2: annual_income gte 30000
  Rule 3: employment_status in_list "employed,self-employed,retired"
  ├── pass → AI Agent [reasoning, outputFormat=json, temperature=0.3]
  │          "Assess risk level (low/medium/high), debt-to-income ratio, and recommendation."
  │            │
  │            ▼
  │          Decision [threshold=0.7]
  │          "Approve if low to medium risk and applicant meets eligibility criteria."
  │          ├── approved → Formatter [email]
  │          │              "Dear {{applicant_name}}, your loan for {{loan_amount}} has been approved."
  │          │                │
  │          │                ▼
  │          │              Output [email]
  │          └── rejected → Output [notification] "Loan rejected"
  └── fail → Output [notification] "Ineligible — does not meet minimum criteria"
```

### Why Validator Before Rule Engine?

- **Validator** catches bad data — missing fields, wrong types, out-of-range values. The workflow halts with a clear error before any logic runs.
- **Rule Engine** applies business eligibility criteria on clean data — deterministic, auditable, no AI.
- **AI Agent** then does the nuanced risk analysis that rules can't capture.

### Debt-to-Income Calculation with Code Runner

You can insert a Code Runner between Input and Rule Engine to calculate derived metrics:

```python
income = float(input_data.get("annual_income", 1))
loan = float(input_data.get("loan_amount", 0))
output = {
    **input_data,                   # pass all original fields through
    "debt_to_income": round(loan / income, 3),
    "monthly_payment": round(loan / 60, 2),  # 5-year term
}
```

Then add a rule: `debt_to_income lte 0.43` (standard 43% DTI limit).

---

## 4. Document Processing Pipeline

**Domain:** Legal, Insurance, Healthcare, Government  
**Trigger:** Document upload (PDF, image, scanned form)  
**Goal:** Extract structured data, classify the document, verify compliance, and route to the right team

### Workflow

```
Input (document[file], document_type[text, optional hint])
  │
  ▼
AI Agent [extraction, outputFormat=json, temperature=0.2]
  "Extract all text and structured fields from this document. Return as JSON with field names."
  │
  ▼
Switch Router [switchField: document_type]
  case_0: invoice|receipt → Invoice Processing Branch
  case_1: contract|agreement → Contract Processing Branch
  case_2: passport|id_card → KYC Branch (see use case #1)
  default → AI Agent [classification] → route manually
```

**Invoice branch:**

```
Switch (case_0)
  │
  ▼
Validator
  - total_amount: required, number, min=0
  - vendor_name: required
  - invoice_date: required, pattern=\d{4}-\d{2}-\d{2}
  │
  ▼
Code Runner [calculate tax and discounts]
  │
  ▼
Aggregator [sum, valueField=line_items, sourceField=items]
  │
  ▼
Output [database] "Store invoice record"
```

### Why Switch Router Here?

Different document types need completely different processing. Switch Router eliminates the need to build separate workflows — one workflow handles all document types, branching at the classification point.

---

## 5. API Data Enrichment with Human Review

**Domain:** Sales, CRM, Research  
**Trigger:** New entity (company/person) to investigate  
**Goal:** Fetch data from an external API, reshape it, run AI analysis, and have a human review before action

### Workflow (built-in sample)

```
Input (entity_id, entity_type)
  │
  ▼
HTTP Request [GET]
  URL: https://api.example.com/entities/{{entity_id}}
  Auth: Bearer token
  │
  ▼
Transform [field_map]
  name → display_name
  email → contact_email
  company.name → employer
  address.city → location
  │
  ▼
AI Agent [reasoning, temperature=0.5]
  "Analyze this entity profile. Identify risk factors, reputation signals, and relevant context."
  │
  ▼
Human Review
  "Review the AI risk analysis. Verify entity details and approve or flag for further review."
  │  (workflow pauses here)
  ▼
Output [database] "Record the review decision"
```

### The Human Review Pause

When the Human Review node executes, the workflow stops and the API returns with `status: "awaiting_review"`. The reviewer sees:
- The previous node's output (AI analysis)
- The review prompt
- The full data that was analyzed

To continue the workflow, the external system (or your team) makes a decision and triggers the next steps through a separate API call or resumes it programmatically.

---

## 6. Customer Support Ticket Routing

**Domain:** SaaS, E-commerce, Telecoms  
**Trigger:** New support ticket submitted  
**Goal:** Classify the issue, determine priority, and route to the right team

### Workflow

```
Input (ticket_id, subject, body, customer_tier)
  │
  ▼
AI Agent [classification, outputFormat=json, temperature=0.3]
  "Classify this support ticket. Return:
   { category: billing|technical|account|feature_request|complaint,
     priority: low|medium|high|urgent,
     sentiment: positive|neutral|negative|angry,
     summary: one sentence }"
  │
  ▼
Rule Engine [OR — escalation triggers]
  Rule 1: priority eq urgent
  Rule 2: sentiment eq angry
  Rule 3: customer_tier eq enterprise
  ├── pass → Human Review "Escalated ticket — needs senior agent"
  └── fail (normal priority)
        │
        ▼
        Switch Router [switchField: category]
        case_0: billing → Output [webhook] → billing team Slack
        case_1: technical → Output [webhook] → engineering Slack
        case_2: account → Output [webhook] → account team Slack
        default → Output [api] → general queue
```

### Why Rule Engine with OR for Escalation?

Any one of the three conditions (urgent priority, angry sentiment, enterprise tier) is sufficient to escalate — you don't need all three. `OR` mode means the `pass` branch fires if at least one rule matches.

---

## 7. Invoice Processing and Validation

**Domain:** Finance, Procurement, Accounts Payable  
**Trigger:** Invoice received via email or upload  
**Goal:** Extract invoice data, validate it, calculate totals, and approve payment

### Workflow

```
Input (invoice[file], vendor_id)
  │
  ▼
AI Agent [extraction, outputFormat=custom_schema, temperature=0.1]
  Schema: {
    "invoice_number": "string",
    "vendor_name": "string",
    "invoice_date": "string",
    "due_date": "string",
    "line_items": [{"description": "string", "quantity": "number", "unit_price": "number", "total": "number"}],
    "subtotal": "number",
    "tax": "number",
    "total_amount": "number",
    "currency": "string"
  }
  │
  ▼
Validator
  - invoice_number: required
  - vendor_name: required
  - total_amount: required, number, min=0.01
  - currency: required, enum=USD,EUR,GBP,CAD
  │
  ▼
Code Runner [verify line item totals match stated total]
  items = input_data.get("line_items", [])
  calculated = sum(item.get("total", 0) for item in items)
  stated = float(input_data.get("subtotal", 0))
  discrepancy = abs(calculated - stated)
  output = {
      **input_data,
      "calculated_subtotal": round(calculated, 2),
      "discrepancy": round(discrepancy, 2),
      "totals_match": discrepancy < 0.01
  }
  │
  ▼
Rule Engine [AND]
  Rule 1: totals_match eq True
  Rule 2: total_amount lte 10000  (auto-approve limit)
  ├── pass → Output [database] "Queue for payment"
  └── fail → Human Review "Invoice discrepancy or over limit — manual approval required"
```

### Why `custom_schema` for Extraction?

Invoice extraction requires a precisely structured output that downstream nodes depend on by field name. `custom_schema` tells the model exactly what JSON shape to return — the validator then enforces it at the data level as a safety net.

---

## 8. Batch Data Aggregation Report

**Domain:** Analytics, Operations, Finance  
**Trigger:** Scheduled run or batch upload  
**Goal:** Compute statistics over a dataset and produce a formatted report

### Workflow

```
Input (dataset[json], report_title)
  │
  ▼
Aggregator [count, sourceField=records]
  │  result → total_count
  ▼
Aggregator [sum, sourceField=records, valueField=amount]
  │  result → total_amount
  ▼
Aggregator [avg, sourceField=records, valueField=amount]
  │  result → average_amount
  ▼
Aggregator [group_by, sourceField=records, groupBy=category]
  │  result → by_category
  ▼
AI Agent [summarization, temperature=0.5]
  "Summarize this dataset. Highlight trends, outliers, and actionable insights."
  │
  ▼
Formatter [markdown]
  Template: |
  # {{report_title}}

  **Total Records:** {{total_count}}
  **Total Amount:** ${{total_amount}}
  **Average Amount:** ${{average_amount}}

  ## AI Summary
  {{result}}
  │
  ▼
Output [report]
```

> Note: In the current version, each Aggregator node processes the same input independently. For chained aggregations, use a Code Runner to compute all metrics at once.

### Code Runner Alternative (All Aggregations in One Node)

```python
records = input_data.get("records", [])
amounts = [float(r.get("amount", 0)) for r in records]
by_cat = {}
for r in records:
    cat = r.get("category", "other")
    by_cat.setdefault(cat, []).append(r.get("amount", 0))

output = {
    "total_count": len(records),
    "total_amount": round(sum(amounts), 2),
    "average_amount": round(sum(amounts)/len(amounts), 2) if amounts else 0,
    "max_amount": max(amounts) if amounts else 0,
    "by_category": {k: {"count": len(v), "total": round(sum(v), 2)} for k, v in by_cat.items()},
}
```

---

## 9. Content Moderation Pipeline

**Domain:** Social Media, Forums, UGC Platforms  
**Trigger:** User-submitted content (text or image)  
**Goal:** Detect policy violations and either auto-remove or escalate for human review

### Workflow

```
Input (content_id, content_type, content[text or file], user_id)
  │
  ▼
AI Agent [classification, outputFormat=json, temperature=0.2]
  "Analyze this content for policy violations.
   Return: { safe: boolean, categories: [hate_speech|spam|adult|violence|misinformation],
   severity: low|medium|high, confidence: 0.0-1.0, reason: string }"
  │
  ▼
Rule Engine [OR]
  Rule 1: safe eq False  AND  severity eq high
  Rule 2: confidence gte 0.95  AND  safe eq False
  ├── pass (clear violation) → Output [webhook] → Auto-remove API
  └── fail (uncertain)
        │
        ▼
        Decision [threshold=0.7]
        "Should this content be removed based on the moderation analysis?"
        ├── approved (remove) → Human Review "High-confidence removal — verify before actioning"
        └── rejected (keep) → Output [api] "Content cleared — no action needed"
```

---

## 10. Multi-language Document Translation

**Domain:** Legal, Publishing, Government, International Business  
**Trigger:** Document submitted for translation  
**Goal:** Detect source language, translate content, and verify quality

### Workflow

```
Input (document[file or text], target_language, document_type)
  │
  ▼
AI Agent [extraction, temperature=0.1]
  "Extract the full text from this document. Preserve structure, headings, and formatting."
  │
  ▼
AI Agent [translation, temperature=0.3]
  "Translate the provided text to {{target_language}}.
   Preserve all formatting, section structure, and technical terminology.
   Return the translated text only."
  │
  ▼
Verification [consistency]
  "Verify the translation is complete, accurate, and no sections were omitted.
   Check that the tone and register match the original."
  │
  ▼
Formatter [html]
  Template: |
  <h1>Translation: {{label}}</h1>
  <p><strong>Target Language:</strong> {{target_language}}</p>
  <div class="translation-body">{{result}}</div>
  │
  ▼
Output [report]
```

---

## Combining Nodes: Design Patterns

### Pattern 1: Validate → Rules → AI

Use this when you have hard constraints (field types, required fields) that must pass before any AI processing. The Validator is the gatekeeper; Rule Engine handles deterministic business logic; AI handles nuance.

```
Validator → Rule Engine → AI Agent → Decision
```

### Pattern 2: Fetch → Transform → AI

Use this when your input is from an external API that returns more data than you need. HTTP fetches everything; Transform extracts only relevant fields before passing them to the AI.

```
HTTP Request → Transform → AI Agent
```

### Pattern 3: AI → Route → Format

Use this when different outcomes need different presentations. The AI makes a decision; routing branches; each branch formats its own message.

```
AI Agent → Decision → (approved) Formatter → Output
                    → (rejected) Formatter → Output
```

### Pattern 4: Enrich + Aggregate

Use this to combine multiple data sources and compute statistics before AI analysis.

```
Input → HTTP (source 1) → Aggregator
      → HTTP (source 2) → Aggregator  → AI Agent → Output
      → Transform       ─────────────┘
```

> In the current single-path execution model, use Code Runner to merge outputs from multiple upstream paths.

---

## Tips for Building Effective Workflows

**Keep AI nodes focused.** Each AI Agent should have one clearly defined job. "Extract data" and "analyze risk" should be two separate AI nodes, not one.

**Set appropriate temperatures.** Extraction and validation: 0.1–0.3 (deterministic). Analysis and reasoning: 0.5–0.7. Creative content: 0.8–1.5.

**Use Validator before Rule Engine.** Validator catches structural data problems (missing field, wrong type). Rule Engine applies business logic on known-clean data.

**Use `custom_schema` for structured extraction.** When downstream nodes need to reference specific fields by name, tell the AI exactly what JSON shape to return. Add a Validator after it as a safety net.

**Put Human Review before irreversible actions.** If your Output node sends emails, charges payments, or modifies a production database, add a Human Review step before it for any workflow handling real data.

**Log and trace first.** Execute a workflow with test data and read the full execution trace before connecting it to live systems. The trace shows exactly what the model received and returned at each step.
