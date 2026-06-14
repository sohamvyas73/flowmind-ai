# Node Reference

Complete reference for all 14 node types. Each section covers what the node does, every configuration field, the structure of its output, and a practical example.

---

## Table of Contents

1. [Input](#1-input-node)
2. [AI Agent](#2-ai-agent-node)
3. [Verification](#3-verification-node)
4. [Decision](#4-decision-node)
5. [Output](#5-output-node)
6. [HTTP Request](#6-http-request-node)
7. [Transform](#7-transform-node)
8. [Human Review](#8-human-review-node)
9. [Rule Engine](#9-rule-engine-node)
10. [Code Runner](#10-code-runner-node)
11. [Validator](#11-validator-node)
12. [Switch Router](#12-switch-router-node)
13. [Formatter](#13-formatter-node)
14. [Aggregator](#14-aggregator-node)

---

## 1. Input Node

**Color:** Blue  
**Handles:** one source (right)

Defines the fields that callers must provide when triggering the workflow. Each field becomes a named key in the JSON body of the `/trigger` API, or a labeled input box in the Execute modal.

### Configuration

| Field | Type | Description |
|---|---|---|
| `label` | string | Display name on the canvas |
| `description` | string | Optional description |
| `fields` | array | List of input field definitions |

Each field in `fields`:

| Key | Values | Description |
|---|---|---|
| `id` | string | Unique field ID (auto-generated) |
| `name` | string | JSON key name — used in API body and `{{template}}` references |
| `type` | `text` \| `file` \| `number` \| `json` | Controls the input widget and how data is passed |

### Output

```json
{
  "inputs": {
    "customer_id": "cust_123",
    "document": "data:application/pdf;base64,..."
  },
  "filenames": {
    "document": "passport.pdf"
  },
  "timestamp": "2025-01-15T10:30:00Z"
}
```

### Trigger API Usage

If your workflow has an Input node with fields `customer_id` (text) and `amount` (number):

```bash
curl -X POST http://localhost:8000/api/v1/workflows/{id}/trigger \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "cust_123", "amount": 4999.00}'
```

---

## 2. AI Agent Node

**Color:** Purple  
**Handles:** one target (left), one source (right)

Makes an LLM call via Google Gemini. The model receives the previous node's output as context plus a system prompt built from `aiTask`, optional custom instructions in `prompt`, and format instructions derived from `outputFormat`.

### Configuration

| Field | Type | Description |
|---|---|---|
| `aiTask` | enum | Determines the system prompt persona |
| `outputFormat` | enum | How the model should structure its response |
| `outputSchema` | string | JSON schema string (only used when `outputFormat = custom_schema`) |
| `temperature` | number (0–2) | Controls randomness. 0 = deterministic, 0.7 = balanced, 2 = creative |
| `prompt` | string | Additional instructions appended to the system prompt |

**`aiTask` options:**

| Value | System prompt |
|---|---|
| `reasoning` | "You are a reasoning agent. Analyze the data and provide detailed insights." |
| `extraction` | "You are a data extraction agent. Extract structured information from the input." |
| `classification` | "You are a classification agent. Categorize the input data accurately." |
| `verification` | "You are a verification agent. Verify the consistency and accuracy of the data." |
| `fraud_detection` | "You are a fraud detection agent. Identify suspicious patterns." |
| `summarization` | "You are a summarization agent. Condense the input into a clear, concise summary." |
| `translation` | "You are a translation agent. Accurately translate the input content." |

**`outputFormat` options:**

| Value | What the model returns |
|---|---|
| `text` | Plain text (default) |
| `json` | Auto-parsed JSON — response is parsed and `result` is a dict, not a string |
| `markdown` | Formatted Markdown |
| `csv` | CSV with header row |
| `html` | HTML content elements (no doctype) |
| `table` | Markdown table with column headers |
| `bullet_list` | Bullet points prefixed with `- ` |
| `custom_schema` | JSON matching the schema you define in `outputSchema` |

### Output

```json
{
  "task": "extraction",
  "result": "Extracted data...",
  "format": "text",
  "confidence": 0.85,
  "timestamp": "2025-01-15T10:30:01Z"
}
```

When `outputFormat` is `json` or `custom_schema`, `result` is a parsed object:

```json
{
  "result": { "name": "John Smith", "score": 742 },
  "format": "json"
}
```

### Multimodal Support

If the previous Input node has a `file` field (PDF, image, etc.), the AI node automatically switches to multimodal mode. Images are passed as `image_url` content parts; PDFs and other files are passed as `media` inline data. The model can read and reason about the file content.

---

## 3. Verification Node

**Color:** Green  
**Handles:** one target (left), one source (right)

Uses the LLM to perform a domain-specific verification check. Unlike AI Agent, the system prompt is fixed to verification-focused instructions, and the node always returns a `pass`/`fail` result with a confidence score.

### Configuration

| Field | Type | Description |
|---|---|---|
| `verificationType` | enum | The type of verification to perform |

**`verificationType` options:**

| Value | What it checks |
|---|---|
| `consistency` | Fields are internally consistent (e.g., dates align, totals add up) |
| `compliance` | Meets regulatory or policy requirements |
| `signature` | Signature validity or authenticity |
| `document` | Document structure and content validity |
| `completeness` | All required fields are present and non-empty |
| `pii_detection` | Detects Personally Identifiable Information |

### Output

```json
{
  "verification_type": "compliance",
  "result": "pass",
  "confidence": 0.9,
  "analysis": "All required fields are present. The document meets the compliance checklist.",
  "timestamp": "2025-01-15T10:30:02Z"
}
```

---

## 4. Decision Node

**Color:** Yellow  
**Handles:** one target (left), two sources: `approved` (top-right, green) and `rejected` (bottom-right, red)

Makes a binary approve/reject decision using the LLM. The model reads the previous node's full output and returns a structured JSON verdict. The routing engine uses `_active_handles` to fire only the matching outgoing edge.

### Configuration

| Field | Type | Description |
|---|---|---|
| `conditionType` | enum | Framing for the decision (`threshold`, `compliance`, `risk`, `rule`) |
| `threshold` | number (0–1) | Minimum confidence required to approve |
| `prompt` | string | Custom decision criteria (replaces the default prompt) |

### Output

```json
{
  "decision": "approved",
  "confidence": 0.91,
  "threshold": 0.8,
  "reasoning": "Credit score of 742 exceeds minimum. Income verified at $85k.",
  "summary": "Loan applicant meets all eligibility criteria.",
  "key_findings": [
    "Credit score: 742 (required: 650)",
    "Income: $85,000/year (required: $30,000)",
    "Employment: Full-time employed"
  ],
  "_active_handles": ["approved"],
  "timestamp": "2025-01-15T10:30:03Z"
}
```

**Routing:** Connect the `approved` handle to the success branch and the `rejected` handle to the failure branch. Only the matching branch executes.

---

## 5. Output Node

**Color:** Indigo  
**Handles:** one target (left), no source

Terminal node. Marks where a workflow branch ends and what to do with the final result.

### Configuration

| Field | Type | Description |
|---|---|---|
| `outputType` | enum | What to do with the output |
| `deliveryUrl` | string | URL for webhook or Slack delivery |

**`outputType` options:**

| Value | Behavior |
|---|---|
| `api` | Return in the API response (default) |
| `database` | Write to database (logged) |
| `notification` | Send a notification (logged) |
| `report` | Generate a report (logged) |
| `webhook` | POST to `deliveryUrl` |
| `slack` | POST to Slack webhook at `deliveryUrl` |
| `email` | Send email (logged; requires integration) |

### Output

```json
{
  "output_type": "api",
  "data": { ... },
  "status": "success",
  "timestamp": "2025-01-15T10:30:04Z"
}
```

---

## 6. HTTP Request Node

**Color:** Orange  
**Handles:** one target (left), one source (right)

Makes an async HTTP request to any external API. Supports `{{template}}` substitution in the URL, headers, and body using values from the previous node's output.

### Configuration

| Field | Type | Description |
|---|---|---|
| `method` | `GET` \| `POST` \| `PUT` \| `PATCH` \| `DELETE` | HTTP method |
| `url` | string | Target URL. Supports `{{field}}` substitution |
| `headers` | array | `[{ key, value }]` — values support `{{field}}` substitution |
| `authType` | `none` \| `bearer` \| `apikey` | Authentication method |
| `authValue` | string | Token or API key value |
| `authHeader` | string | Header name for `apikey` auth (default: `X-API-Key`) |
| `bodyTemplate` | string | JSON template for POST/PUT/PATCH body. Supports `{{field}}` |
| `timeout` | number | Request timeout in seconds (default: 30) |

### Template Substitution

Any `{{field}}` in the URL, headers, or body is replaced with the corresponding value from the previous node's output. Dot notation is supported: `{{user.address.city}}`.

```
URL: https://api.example.com/users/{{customer_id}}/profile
Body: { "name": "{{full_name}}", "email": "{{contact_email}}" }
```

### Output

```json
{
  "status_code": 200,
  "success": true,
  "response": { "id": 1, "name": "Leanne Graham", "email": "..." },
  "url": "https://api.example.com/users/1",
  "method": "GET",
  "timestamp": "2025-01-15T10:30:05Z"
}
```

---

## 7. Transform Node

**Color:** Teal  
**Handles:** one target (left), one source (right)

Reshapes data without an LLM. Three modes: rename fields, render a JSON template, or filter to a subset of keys. Pure Python — no AI call, no latency.

### Configuration

| Field | Type | Description |
|---|---|---|
| `transformMode` | `field_map` \| `template` \| `filter` | Which transform to apply |
| `fieldMappings` | array | `[{ from, to }]` — for `field_map` mode |
| `template` | string | JSON template string — for `template` mode |
| `filterKeys` | string | Comma-separated field names to keep — for `filter` mode |

**Mode: `field_map`**

Renames and picks fields. Source keys support dot notation (`user.name`).

```
from: "company.name"  →  to: "employer"
from: "email"         →  to: "contact_email"
```

**Mode: `template`**

Builds a new JSON object using `{{field}}` placeholders:

```json
{
  "userId": "{{id}}",
  "displayName": "{{name}}",
  "company": "{{company.name}}"
}
```

**Mode: `filter`**

Keeps only the specified top-level keys: `customer_id, full_name, score`

### Output

```json
{
  "transformed": {
    "employer": "Romaguera-Crona",
    "contact_email": "sincere@april.biz"
  },
  "source_keys": ["id", "name", "email", "company"],
  "mode": "field_map",
  "timestamp": "2025-01-15T10:30:06Z"
}
```

---

## 8. Human Review Node

**Color:** Rose  
**Handles:** one target (left), one source (right)

Pauses workflow execution and surfaces the previous node's output for manual review. The workflow status is saved as `completed` (paused) in the database and execution stops at this node. A human then reviews the data and decides to approve or continue through an external system.

### Configuration

| Field | Type | Description |
|---|---|---|
| `reviewPrompt` | string | Instructions shown to the reviewer |

### Output

```json
{
  "status": "awaiting_review",
  "review_prompt": "Please verify the extracted fields and approve before proceeding.",
  "data_to_review": { ... },
  "message": "Workflow paused — awaiting human review",
  "timestamp": "2025-01-15T10:30:07Z"
}
```

The workflow halts here. The `data_to_review` field contains the sanitized output of the previous node (binary data is stripped).

---

## 9. Rule Engine Node

**Color:** Amber  
**Handles:** one target (left), two sources: `pass` (top-right, green) and `fail` (bottom-right, red)

Evaluates a set of business rules against the previous node's output. No LLM — pure deterministic logic. Routes via the `pass` handle if rules are met or the `fail` handle if not.

### Configuration

| Field | Type | Description |
|---|---|---|
| `combineMode` | `AND` \| `OR` | `AND`: all rules must pass. `OR`: at least one must pass |
| `rules` | array | List of rule conditions |

Each rule:

| Key | Description |
|---|---|
| `field` | Dot-notation field path (e.g., `credit_score`, `user.age`) |
| `operator` | One of 18 operators (see table below) |
| `value` | Expected value (not used for existence/emptiness operators) |
| `label` | Human-readable label shown in the execution trace |

### Supported Operators

| Category | Operator | Description |
|---|---|---|
| Equality | `eq` | equals |
| | `neq` | not equals |
| Numeric | `gt` | greater than |
| | `gte` | greater or equal |
| | `lt` | less than |
| | `lte` | less or equal |
| | `between` | between `lo,hi` (inclusive) |
| Text | `contains` | substring match (case-insensitive) |
| | `not_contains` | does not contain |
| | `starts_with` | starts with prefix |
| | `ends_with` | ends with suffix |
| | `regex` | Python regex match |
| List | `in_list` | value in `a,b,c` |
| | `not_in_list` | value not in list |
| Existence | `exists` | field is present and not null |
| | `not_exists` | field is absent or null |
| | `is_empty` | field is falsy (empty string, 0, [], {}) |
| | `is_not_empty` | field is truthy |

### Output

```json
{
  "passed": true,
  "route": "pass",
  "matched_rules": ["Min credit score", "Min income", "Employment check"],
  "failed_rules": [],
  "combine_mode": "AND",
  "rule_count": 3,
  "data": { ... },
  "_active_handles": ["pass"],
  "timestamp": "2025-01-15T10:30:08Z"
}
```

---

## 10. Code Runner Node

**Color:** Zinc  
**Handles:** one target (left), one source (right)

Executes a Python snippet in a sandboxed environment. The previous node's output is available as `input_data`. Assign to `output` to return a value.

### Configuration

| Field | Type | Description |
|---|---|---|
| `code` | string | Python code to execute |
| `timeout` | number | Maximum execution time in seconds (default: 10, max: 60) |

### Available Built-ins

The sandbox allowlists these names:

- **Types:** `str`, `int`, `float`, `bool`, `list`, `dict`, `set`, `tuple`
- **Built-ins:** `len`, `range`, `enumerate`, `sorted`, `reversed`, `sum`, `min`, `max`, `abs`, `round`, `zip`, `map`, `filter`, `any`, `all`, `isinstance`, `hasattr`, `getattr`, `type`, `repr`, `print`
- **Modules:** `json`, `re`, `math`, `datetime`
- **Not available:** `import`, `open`, `os`, `subprocess`, `sys`, `eval`, `exec` (other than the code itself)

### Examples

```python
# Score calculation
score = input_data.get("credit_score", 0)
income = input_data.get("annual_income", 0)
debt_ratio = input_data.get("loan_amount", 0) / income if income > 0 else 99
output = {
    "risk_score": round(score / 10 + (1 - debt_ratio) * 50, 2),
    "debt_to_income": round(debt_ratio, 3),
}
```

```python
# Extract numbers from text
import re
text = input_data.get("result", "")
numbers = re.findall(r'\d+(?:\.\d+)?', text)
output = {"extracted_numbers": [float(n) for n in numbers]}
```

### Output

```json
{
  "output": { "risk_score": 87.4, "debt_to_income": 0.12 },
  "executed": true,
  "timestamp": "2025-01-15T10:30:09Z"
}
```

On timeout:
```json
{ "error": "Code execution timed out after 10s" }
```

---

## 11. Validator Node

**Color:** Emerald  
**Handles:** one target (left), one source (right)

Validates fields in the previous node's output against configurable rules. If any validation fails, the workflow **halts** — it does not route to a "fail" branch. Use Rule Engine instead if you want branching on failure.

### Configuration

| Field | Type | Description |
|---|---|---|
| `validationRules` | array | List of field validation definitions |

Each rule:

| Key | Description |
|---|---|
| `field` | Dot-notation field path |
| `required` | `"true"` — halt if field is missing or empty |
| `fieldType` | `string`, `number`, `boolean`, `array`, `object` — type check |
| `pattern` | Regex pattern the string value must match |
| `min` / `max` | Minimum/maximum numeric value |
| `minLength` / `maxLength` | Minimum/maximum string or array length |
| `enum` | Comma-separated list of allowed values |

### Output (pass)

```json
{
  "passed": true,
  "errors": [],
  "rule_count": 4,
  "data": { ... },
  "timestamp": "2025-01-15T10:30:10Z"
}
```

### Output (fail — halts workflow)

```json
{
  "passed": false,
  "errors": [
    "'credit_score' (250) is below minimum 300",
    "'employment_status' 'unemployed' not in ['employed', 'self-employed', 'retired']"
  ],
  "error": "Validation failed (2 errors): 'credit_score' (250) is below minimum 300",
  "timestamp": "2025-01-15T10:30:10Z"
}
```

---

## 12. Switch Router Node

**Color:** Violet  
**Handles:** one target (left), one source per case (right, dynamic) + `default` source

Routes to one of N branches based on the value of a specific field. Use `|` in the match value to match multiple values on one branch.

### Configuration

| Field | Type | Description |
|---|---|---|
| `switchField` | string | Dot-notation field path to read (e.g., `document_type`) |
| `cases` | array | Ordered list of match cases |

Each case:

| Key | Description |
|---|---|
| `matchValue` | Value to match. Use `|` for OR: `invoice|receipt` |
| `handle` | Source handle ID (auto-assigned as `case_0`, `case_1`, ...) |
| `label` | Human-readable label |

Unmatched values route via the `default` handle. Match order is top to bottom — first match wins.

### Example

For field `document_type`:

| Case | Match value | Handle |
|---|---|---|
| 1 | `passport|national_id` | `case_0` |
| 2 | `invoice|receipt` | `case_1` |
| 3 | `contract` | `case_2` |
| default | (anything else) | `default` |

### Output

```json
{
  "routed_to": "case_1",
  "matched_case": "invoice|receipt",
  "switch_field": "document_type",
  "switch_value": "invoice",
  "data": { ... },
  "_active_handles": ["case_1"],
  "timestamp": "2025-01-15T10:30:11Z"
}
```

---

## 13. Formatter Node

**Color:** Lime  
**Handles:** one target (left), one source (right)

Renders a text template with `{{field}}` substitution from the previous node's output. Designed for producing the final human-readable output — email bodies, Slack messages, HTML reports, or plain text summaries.

### Configuration

| Field | Type | Description |
|---|---|---|
| `outputFormat` | `text` \| `html` \| `markdown` \| `email` \| `slack` | Controls metadata; the template itself determines content |
| `subjectTemplate` | string | Subject/title line (email, Slack). Supports `{{field}}` |
| `template` | string | Body template with `{{field}}` placeholders |

### Example

```
outputFormat: email
subjectTemplate: "Loan Decision: {{applicant_name}}"
template: |
  Dear {{applicant_name}},

  Your loan application for {{loan_amount}} has been {{decision}}.

  Confidence: {{confidence}}
  Reason: {{reasoning}}

  Best regards,
  Loan Team
```

### Output

```json
{
  "rendered": "Dear John Smith,\n\nYour loan application for 50000 has been approved...",
  "subject": "Loan Decision: John Smith",
  "format": "email",
  "timestamp": "2025-01-15T10:30:12Z"
}
```

---

## 14. Aggregator Node

**Color:** Sky  
**Handles:** one target (left), one source (right)

Performs a statistical or collection operation over an array field in the previous node's output. No LLM.

### Configuration

| Field | Type | Description |
|---|---|---|
| `sourceField` | string | Dot-notation path to the array. Leave blank to auto-detect the first array found |
| `operation` | enum | What to compute (see table below) |
| `valueField` | string | Field within each array item to use for numeric operations |
| `groupBy` | string | Field to group by (only for `group_by` operation) |
| `separator` | string | Join separator (only for `join` operation, default: `, `) |

### Operations

| Operation | Description | Returns |
|---|---|---|
| `count` | Total number of items | number |
| `sum` | Sum of `valueField` across items | number |
| `avg` | Mean of `valueField` | number (4 decimal places) |
| `min` | Minimum `valueField` | number |
| `max` | Maximum `valueField` | number |
| `first` | First item in the array | any |
| `last` | Last item in the array | any |
| `join` | Concatenate `valueField` strings with `separator` | string |
| `unique` | Deduplicated list of `valueField` values | array |
| `group_by` | Group items by `groupBy` field | object `{key: [items]}` |

### Output

```json
{
  "result": 4327.50,
  "operation": "sum",
  "source_field": "transactions",
  "item_count": 12,
  "timestamp": "2025-01-15T10:30:13Z"
}
```

---

## Routing Nodes Summary

Three nodes use `_active_handles` to control conditional branching:

| Node | Handles | When each fires |
|---|---|---|
| Decision | `approved`, `rejected` | Based on LLM decision |
| Rule Engine | `pass`, `fail` | Based on rule evaluation |
| Switch Router | `case_0`...`case_N`, `default` | Based on field value match |

Non-routing nodes have no `_active_handles` in their output — all their outgoing edges fire unconditionally.
