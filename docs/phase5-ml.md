# Phase 5 — ML nodes (technical reference)

Beginners: read the [ML guide](ml-guide.md).

## Principles

1. **FlowMind does not execute model code.** Scoring is an HTTP call to the customer's endpoint; the registry is reached
   over MLflow's REST API. A malicious or poisoned model artifact cannot run inside FlowMind (no `pickle.load`, no
   `mlflow.pyfunc.load_model`).
2. **Explicit, never guessed.** Every node needs a user-chosen connection; `features` are required (no implicit
   "all columns"), so private columns are never sent by accident.
3. **Reuse the platform.** Connections are encrypted, SSRF-guarded and allow-listed like every other connection; results
   are `DatasetRef` tables with PII tagging, lineage and billing.

## Components

| Module | Role |
|---|---|
| `app/connectors/ml.py` | Connection types `mlflow` and `ml_endpoint` (test = tracking-server ping / endpoint `/ping`) |
| `app/ml/mlflow_client.py` | SSRF-safe REST client: models, versions, run metrics, alias get/set; name/alias validation |
| `app/ml/endpoints.py` | Request formats (`mlflow_records`, `mlflow_split`, `records`), prediction normalisation, health |
| `app/ml/drift.py` | PSI for numeric (reference-quantile bins, missing bucket) and categorical columns; pure functions |
| `app/services/ml_nodes.py` | The five nodes |
| `app/models/ml.py` | `ml_feedback_batches` (aggregates only) |
| `app/api/ml.py` | `/ml/...` endpoints used by the Models page |

## Nodes

**Predict** (`predictNode`) — `connectionId`, `features[]`, `autoNumbers`. One record from the previous node's output.
Output: `prediction, probability, prediction_id, features, model_endpoint, latency_ms`. A table upstream is refused ("use Batch Score").

**Batch Score** (`batchScoreNode`) — `connectionId`, `features[]`, `outputColumn` (default `prediction`, must not exist),
`batchSize` (≤1000), `maxRows` (default 100,000, max 500,000; larger tables are refused, not truncated). Streams the table
in two passes (score, then write Parquet with the new column(s)); `<output>_proba` is added when the endpoint returns class
probabilities. Lineage edges: `dataset:<id>` (operation `score`) and `flowmind://models/<connection>`. Not run in Preview
(external calls). Output extras: `scored_rows, requests, avg_latency_ms, prediction_summary`.

**Drift Check** (`driftCheckNode`) — `referenceFile`, `columns[]`, `warnAt` (0.1), `alertAt` (0.25), `onDrift` (`stop|warn`).
Passes the table through unchanged and adds a `drift` report (per column: PSI, status, means/missing or top changed
categories). IDs/free text (>50% distinct values) and PII-tagged columns are skipped unless named. Runs in Preview.

**Feedback** (`feedbackNode`) — `modelName`, `taskType` (`classification|regression`), `predictionColumn`, `actualColumn`,
`threshold`, `onFail` (`warn|stop`). Table mode or single-record mode. Classification → accuracy + per-class counts;
regression → MAE (+RMSE, bias). Writes one `ml_feedback_batches` row (not in Preview). Output: `feedback` report with `breached`.

**Promote Model** (`registryPromoteNode`) — `connectionId` (**read-write** MLflow), `modelName`, `version` (`latest`,
a number, or `{{field}}`), `alias`, `gates[{metric,op,value}]`, `beatCurrent` + `compareMetric` + `higherIsBetter`, `onFail`
(`stop|skip`). Reads run metrics, evaluates gates, then `POST /registered-models/alias`. Idempotent. Not run in Preview.

## API (`/api/v1/ml`)

| Method & path | Purpose |
|---|---|
| `GET /connections/{id}/models` | Registered models, recent versions, aliases, training metrics |
| `POST /endpoints/{id}/score` | "Try it": score one record against a model-endpoint connection |
| `GET /feedback?model=` | Feedback history, newest first |

## Billing

Predict 2 · Batch Score 3 (+1 per full 10,000 rows) · Drift Check 1 · Feedback 1 · Promote 1. A node that errors before doing
work is not billed; a Drift Check or Feedback that *ran and fired its gate* is. Preview is free (Drift Check runs; the others skip).

## Security

* Endpoint and MLflow URLs go through the SSRF guard; private hosts need admin allow-listing per connection.
* Tokens are encrypted at rest and masked in the API; error text never echoes them.
* Model and alias names are validated against strict patterns before being placed in a query or path.
* Promotion requires a read-write connection and passes gates first; failed gates change nothing.
* Feedback stores aggregates only. Batch Score sends only the listed features.

## Verification

`backend/tests/test_ml.py` (50 tests): drift maths (stable/shifted/moderate/categorical/missing/constant/all-missing/ordering),
metrics, response shapes, payload formats, gates, validation; all five nodes end to end through real workflow runs against
in-process fake scoring and MLflow servers (billing, preview, lineage, privacy, error paths, read-only protection, beat-the-champion);
plus **three tests against a real MLflow 3.17 server and a real scikit-learn model served with `mlflow models serve`**
(`ML_TEST_MLFLOW_URL`, `ML_TEST_ENDPOINT_URL`): connection tests, 400-row batch score with feedback accuracy > 0.75, and a
promote → already-promoted round trip.

**Not verified here:** SageMaker / Vertex / Hugging Face endpoints (any that accept the supported JSON shapes should work),
authenticated MLflow servers (token/basic auth is implemented, not exercised), MLflow versions other than 3.17, very large
tables (>500k rows is refused by design).

## Not in this phase

Training / AutoML, shadow scoring, A/B routing, feature lookup (feature store), and dedicated SageMaker/Vertex adapters.
MLflow *stages* (deprecated upstream) are not supported; use aliases.
