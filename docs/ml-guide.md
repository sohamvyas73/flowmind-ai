# Machine-learning nodes — a beginner-friendly guide

You do not need to know how to build a model. This guide shows how to **use** a model your data team already has —
score customers with it, notice when it goes stale, and promote a better version safely.

> **FlowMind never runs your model itself.** It talks to *your* model-scoring endpoint and *your* MLflow registry, using
> connections you add on purpose. A model file from a registry therefore can never run code inside FlowMind, and nothing is
> chosen for you: every ML node refuses to run until you pick a connection.

| I want to… | Use this node |
|---|---|
| get a prediction for **one** customer / record | **Predict** |
| get predictions for **a whole table** | **Batch Score** |
| know if today's data looks different from what the model learned on | **Drift Check** |
| know whether the model is still right (vs what really happened) | **Feedback** |
| make a new model version the live one — only if it is good enough | **Promote Model** |

---

## 0. What you need (once)

Two connections (**Connections** page):

| Connection type | What it is | Example URL |
|---|---|---|
| **Model endpoint** | A web address that returns predictions | `http://localhost:5001/invocations` |
| **MLflow** | Your model registry (versions, metrics, aliases) | `http://localhost:5000` |

![New MLflow connection](images/gallery/11-ml/09-new-mlflow-connection.png)

*Local addresses need an admin to allow-list the host (`localhost` / `127.0.0.1`) on the connection, because FlowMind
blocks private network addresses by default.*

**No MLflow yet? Make a demo one in two minutes** (everything is synthetic):

```bash
pip install mlflow scikit-learn pandas
mlflow server --host 127.0.0.1 --port 5000 &                                  # the registry
python scripts/mlflow_demo.py http://127.0.0.1:5000                            # trains + registers "churn-model" v1 and v2
mlflow models serve -m "models:/churn-model/2" -p 5001 --env-manager local     # a scoring endpoint
```

Then on the **Models** page you can see the registry and try the endpoint:

![Models page](images/gallery/11-ml/07-models-registry-and-try-it.png)

---

## 1. Predict — one record

Load the sample **ML: Will this customer churn? (one record)**, pick your endpoint, and run it with
`tenure_months = 3, monthly_spend = 40.5, support_tickets = 5`.

![Predict](images/gallery/11-ml/01-predict-one-record.png)

* **Features** are the fields the model was trained on. You list them yourself — nothing is guessed, so a private field
  such as an email can never be sent to the model by accident.
* Numbers typed as text (`"40.5"`) are converted to numbers for you.
* Output: `prediction`, `probability` (if the model gives one), `prediction_id`, `latency_ms`.

## 2. Batch Score — a whole table

Sample **ML: Score customers for churn**: *Load Data (`churn_customers.csv`) → Batch Score → Summarise*.
The table gets a new `prediction` column; the original columns stay.

![Batch Score](images/gallery/11-ml/02-batch-score-results.png)

Real result with the demo model: 400 customers → **200 predicted to stay (0), 200 predicted to churn (1)**, in 2 requests
(200 rows each), about 56 ms per request.

Only the columns you listed are sent. The result is a normal table: preview it, download it, join it, chart it.
Limits: 100,000 rows per run by default (500,000 max) — filter first if you have more. If the endpoint fails midway the
error says at which row it stopped (`Scoring stopped at row 201: …`).

## 3. Drift Check — has the world changed?

A model is only good while new data looks like its training data. **Drift Check** compares this week's table with a
**reference file** (your training data) using the *Population Stability Index (PSI)*:

| PSI | Meaning |
|---|---|
| under **0.1** | stable |
| **0.1 – 0.25** | moderate shift — keep an eye on it |
| over **0.25** | significant drift — the model may be wrong now |

Sample **ML: Watch for data drift** compares `churn_this_week.csv` (newer customers with more support tickets) with
`churn_reference.csv`:

![Drift detected](images/gallery/11-ml/04-drift-detected.png)

| Column | PSI | Reference mean → now | Verdict |
|---|---|---|---|
| tenure_months | 4.76 | 36.4 → 13.9 | **drift** |
| monthly_spend | 1.50 | 58.5 → 42.7 | **drift** |
| support_tickets | 0.95 | 1.48 → 3.03 | **drift** |

`customer_id` is skipped automatically ("looks like an ID — almost every value is different"), and personal-data
columns are never compared unless you ask for them by name. Choose **Stop the run** (default) to block scoring on shifted
data, or **Warn and continue**.

## 4. Feedback — is it still right?

Once you know what *actually* happened (did the customer really churn?), compare it with the prediction. Sample
**ML: Score and check accuracy** scores customers whose outcome is known, then records how often the model was right:

![Feedback](images/gallery/11-ml/03-feedback-accuracy.png)

The real demo model scored **88.0% accuracy over 400 rows**. Each run adds a point to the history on the **Models** page,
so a slow decline is visible. Set a threshold ("warn / stop below 0.80") to turn it into an alarm — for example, to stop a
pipeline or trigger a retraining workflow. For numeric predictions choose *Regression*: you get the average error (MAE),
RMSE and bias instead.

Only a summary is stored (accuracy, rows, per-class counts) — **never your rows**.

## 5. Promote Model — safely make a version "live"

MLflow lets you point an **alias** (such as `champion`) at a model version; your serving setup follows the alias.
**Promote Model** moves the alias — but only if the gates pass:

![Promote](images/gallery/11-ml/05-promote-model.png)

* **Gates** read the version's own training metrics from MLflow (`accuracy >= 0.85`).
* **Must beat the current model** compares the candidate with whichever version holds the alias now.
* **If a gate fails**: *Stop the run* (default) or *Skip promotion and continue*. Nothing changes in the registry.
* Needs an MLflow connection set to **Read & write** (read-only connections are refused, with a message saying so).
* Want a human to approve first? Put a **Human Review** node in front of it.

Re-running is safe: *"v2 already has the alias 'champion'"*.

---

## Putting it together

```
Load new customers → Drift Check ──(stop if drifted)
                        │
                        ▼
                    Batch Score → Feedback (on yesterday's known outcomes) → …
```

Schedule it from the **Runs** page. A failed Drift Check or a Feedback "worse than threshold" is a signal to retrain —
and when a retrained version is ready, **Promote Model** (with gates) puts it live.

## Common questions

**Which models work?** Anything behind an HTTP endpoint that accepts JSON rows and returns `{"predictions": [...]}`
(that is what `mlflow models serve` does). Other request shapes: *mlflow_split* and plain *records*. SageMaker/Vertex/Hugging
Face endpoints work if they accept those shapes; dedicated adapters come later.

**Is my data sent somewhere?** Yes — the listed feature columns go to the endpoint **you** chose (that is the point). Use an
endpoint you trust, and keep personal columns out of the feature list.

**What does it cost?** Predict 2 credits, Batch Score 3 (+1 per 10,000 rows), Drift Check 1, Feedback 1, Promote 1. Failed
nodes that did no work are not billed. Your own endpoint's compute is yours.

**Can FlowMind train models?** Not yet — train wherever you like and register in MLflow; FlowMind consumes and governs.
