# Data Pipelines — a beginner-friendly guide

This guide teaches the data features of FlowMind **in the simplest form**. You do not need to know SQL, Python or
"data engineering". If you can use a spreadsheet, you can follow along. Engineers: skip to
[Pro mode: the SQL node](#6-pro-mode-the-sql-node) or read the
[technical reference](phase2-data-engine.md).

![Data page](images/gallery/06-data/01-data-page.png)

More screens: [screenshot gallery](screenshots.md#data-pipelines).

> **Everything here uses example files that ship with FlowMind.** One click loads them, so you can follow every
> step and compare your result with the tables below. They are all real outputs, not mock-ups.

---

## 1. The big idea in one minute

A **data pipeline** is a recipe for turning raw data into something useful:

```mermaid
flowchart LR
    A["📄 Load Data<br/>(a file or a database table)"] --> B["🧹 Clean<br/>fix the mess"]
    B --> Q["✅ Quality Check<br/>stop bad data early"]
    Q --> C["🔗 Combine<br/>add info from another table"]
    C --> D["Σ Summarise<br/>totals, counts, averages"]
    D --> E["📊 Result table<br/>download or feed AI"]
```

Each box is a **node**. (The **Quality Check** box is optional but strongly recommended: it is the smoke alarm of your pipeline.) You drag nodes onto the canvas, connect them with lines, and set a few options. The data
flows left to right, and every node hands a **table** (rows and columns, like a spreadsheet tab) to the next.

Three words you will see everywhere:

| Word | Plain meaning | Example |
|---|---|---|
| **Table / dataset** | Rows and columns of data | `orders.csv` has 43 rows and 7 columns |
| **Node** | One step of the recipe | "Remove duplicate rows" |
| **Preview** | A free test run on a small sample that shows what each step produced | The **Preview data** button |

### Preview vs. Execute (important!)

| | **Preview data** | **Execute** |
|---|---|---|
| What it does | Runs the data steps on a **small sample** (up to 1,000 rows) | Runs the **whole thing** |
| Costs credits? | **No** | Yes (a few credits, see [costs](#10-limits-costs-and-privacy)) |
| Calls AI / web / KYC nodes? | **No** (they are skipped) | Yes |
| Saves results? | Only for a day | Saves tables you can download |
| Use it for | Checking your recipe while you build | The real run |

**Rule of thumb: build with Preview, finish with Execute.**

---

## 2. Quickstart — your first pipeline in 5 minutes

1. **Load the example data.** Click **Data** in the top bar, then **Load example data**. Four files appear:
   `messy_contacts.csv`, `sales.csv`, `orders.csv`, `customers.csv`.
2. **Open a ready-made pipeline.** Go back to the canvas. In the left panel, under **Sample Workflows**, find
   **Data: Sales by region** and click **Load**. You will see two nodes: *Daily sales* → *Revenue by region*.
3. **Click Preview data** (in the top bar). A window opens showing every step, the table it produced, and the SQL
   that was run. You should see:

| region | total_revenue | total_units |
|---|---|---|
| East | 214861 | 221 |
| North | 253369 | 232 |
| South | 260327 | 248 |
| West | 229966 | 195 |

4. **Click Execute → Run Workflow.** The same table is now saved.
5. **Go to Data → Pipeline outputs** and download it as **CSV** (opens in Excel/Sheets) or **Parquet**.

![Data page](images/data-outputs.png)

That's a complete pipeline: *load → summarise → result*. Everything below is just more nodes.

---

## 3. Getting data in

### Option A — upload a file (easiest)

**Data → Upload** (or drag a file onto the page). Supported: **CSV, TSV, JSON, JSON-lines, Parquet**, up to 25 MB each.
FlowMind reads the file immediately, so a broken file is rejected right away with a clear message instead of failing
later in the middle of a run.

Click **Preview** next to any file to see its columns, their types and the first rows.

![File preview](images/data-file-preview.png)

**Profile** (next to Preview) tells you what is *in* the file before you build anything: for every column, how many
values are empty, how many different values there are, and the smallest and largest. It also suggests quality checks
(see [Quality checks](#-quality-check--stop-bad-data-early)). For `orders_dirty.csv`:

| Column | Type | Empty | Different values | Smallest | Largest |
|---|---|---|---|---|---|
| order_id | BIGINT | 0 (0.0%) | 15 | 2000 | 2014 |
| customer_id | BIGINT | 1 (6.2%) | 7 | 1 | 7 |
| order_date | VARCHAR | 0 (0.0%) | 9 | 2026-03-01 | yesterday |
| product | VARCHAR | 0 (0.0%) | 6 | Backpack | Water Bottle |
| quantity | BIGINT | 0 (0.0%) | 7 | -2 | 500 |
| unit_price | BIGINT | 1 (6.2%) | 6 | 120 | 2499 |
| status | VARCHAR | 0 (0.0%) | 5 | DELIVERED | shipped |

Spot the problems already: `customer_id` has an empty value, `order_date` has the word `yesterday` as its "largest"
value (so it is text, not a date), `quantity` ranges from -2 to 500, and `status` has 5 spellings of 3 statuses.

![Profile of a file](images/data-profile.png)

> **Privacy by default.** Columns that look sensitive (names like `email`, `phone`, `aadhaar`, `pan`, `address`,
> `password`, `salary`…) are tagged **pii** and their values are shown as `[REDACTED]` in previews and stored results.
> The real values are still used inside your pipeline — only what is *displayed and saved for viewing* is masked.
> FlowMind looks at the **values** too, not just the column name: a column called `contact` that holds email
> addresses, or a column of valid Aadhaar / PAN / card / IBAN numbers, is detected and masked automatically.
> (Detection checks a sample of the rows and, for numbers with check digits, validates the check digit, so ordinary
> IDs such as `1001` are not flagged.)

### Option B — read a database table

1. **Connections → New connection → PostgreSQL**, fill in host, database, user and password, then **Test**.
2. In a **Load Data** node choose **A database table**, pick the connection and the table.

Connections are **read-only by default** and passwords are stored encrypted. Databases on private networks must be
allow-listed by an admin. Details: [Phase 1 guide](phase1-foundation.md).

---

## 4. The nodes (with before → after)

Open any node by clicking it; its settings appear on the right. Column names are offered as clickable chips once you
have run **Preview data** at least once.

### 📄 Load Data — "start here"

Reads one file or one database table into the pipeline.

| Setting | What it means |
|---|---|
| Where is the data? | An uploaded file, or a database table |
| File / Connection + Table | Which one |
| Only these columns | (database) Load fewer columns — faster |
| Max rows | Stop after N rows. Blank = everything (up to 1,000,000) |

`messy_contacts.csv` — notice the stray spaces, the blank name, the repeated rows and the missing cities:

| name | email | city | age |
|---|---|---|---|
|   Asha Patel  | [REDACTED] | Mumbai |  |
| Ben Carter | [REDACTED] | London | 42 |
| Ben Carter | [REDACTED] | London | 42 |
| chloe dubois | [REDACTED] |  |  |
| Dev Sharma  | [REDACTED] | Delhi | 31 |
|  | [REDACTED] | Nowhere | 25 |

*…and 3 more rows*

### 🧹 Clean — "fix the mess"

Every option you tick becomes a step of one SQL query (you can read it in the preview).

| Option | What it does |
|---|---|
| Trim extra spaces | `"  Asha Patel "` → `"Asha Patel"` |
| Remove duplicate rows | Keeps one copy of identical rows |
| Drop rows where these are empty | Removes rows with a blank/missing value in the chosen columns |
| Fill empty values | Replaces blanks in a column with a value you choose |
| Change text case | `lowercase` or `UPPERCASE` for chosen columns |
| Rename columns | `city` → `town` |
| Keep only these columns | Throw away the rest |
| **Protect personal data** | Replace a column with a **hash** (one-way fingerprint), a **mask** (`******atel`), `[REMOVED]`, or **blank** it |

Settings used in the quick tutorial: trim all, remove duplicates, drop rows with empty **name**, fill empty **city**
with `Unknown`, lowercase **email**. Result — 9 rows became 6:

| name | email | city | age |
|---|---|---|---|
| Ben Carter | [REDACTED] | London | 42 |
| chloe dubois | [REDACTED] | Unknown |  |
| Elena Rossi | [REDACTED] | Rome |  |
| Farah Khan | [REDACTED] | Dubai | 29 |
| Asha Patel | [REDACTED] | Mumbai |  |
| Dev Sharma | [REDACTED] | Delhi | 31 |

*(Emails show `[REDACTED]` because they are personal data. They really were trimmed and lower-cased.)*

The SQL this node wrote for you — copy it anywhere:

```sql
WITH s1 AS (SELECT * REPLACE (trim("name") AS "name", trim("email") AS "email", trim("city") AS "city", trim("age") AS "age") FROM input),
s2 AS (SELECT * REPLACE (lower("email") AS "email") FROM s1),
s3 AS (SELECT * FROM s2 WHERE NOT (("name" IS NULL OR trim("name") = ''))),
s4 AS (SELECT * REPLACE (COALESCE(NULLIF(trim("city"), ''), 'Unknown') AS "city") FROM s3)
SELECT DISTINCT * FROM s4
```

**Protect personal data.** When a column holds personal data, you often still need *something* to join or count on,
without exposing the real value. Hashing keeps rows matchable; masking keeps a hint; redact/blank remove it.
Customers with email **hashed**, name **masked**, city **redacted**:

| customer_id | name | contact_hash | city | tier |
|---|---|---|---|---|
| 1 | ******atel | 21cc2e2de7f6 | [REMOVED] | gold |
| 2 | ******rter | 2ec0798d88b2 | [REMOVED] | silver |
| 3 | ********bois | 5f844dda35f7 | [REMOVED] | gold |
| 4 | ******arma | 1eeadc060bbc | [REMOVED] | bronze |

```sql
SELECT * REPLACE (sha256(CAST("email" AS VARCHAR)) AS "email", CASE WHEN "name" IS NULL THEN NULL ELSE repeat('*', greatest(length(CAST("name" AS VARCHAR)) - 4, 0)) || right(CAST("name" AS VARCHAR), 4) END AS "name", CASE WHEN "city" IS NULL THEN NULL ELSE '[REMOVED]' END AS "city") FROM input
```

> **Tip:** a plain hash of something guessable (a 10-digit phone number) can be reversed by trying every number. Add a
> secret **salt** in the node to prevent that. After Preview, the editor even offers a one-click "Personal data
> detected in: … — protect them" button.

![Protect personal data](images/protect-personal-data.png)

### 🔗 Combine — "add information from another table"

Joins two tables side by side by matching a column — like a spreadsheet **VLOOKUP**. Connect **two** nodes into it:
the first connection is the **left** table, the second is the **right**.

| Setting | What it means |
|---|---|
| Swap left and right | If you connected them in the wrong order |
| Keep… | **inner** = only rows that match on both sides · **left** = every left row, plus matches · **right** = every right row, plus matches · **full** = everything from both |
| Match rows where | The matching columns, e.g. `customer_id = customer_id` |

Orders (left) + customers (right), matched on `customer_id`. Each order now also knows who bought it:

| order_id | customer_id | order_date | product | quantity | unit_price | status | name | email | city | tier |
|---|---|---|---|---|---|---|---|---|---|---|
| 1000 | 3 | 2026-03-01 | Desk Lamp | 1 | 749 | delivered | Chloe Dubois | [REDACTED] | Paris | gold |
| 1001 | 2 | 2026-03-01 | Headphones | 1 | 2499 | cancelled | Ben Carter | [REDACTED] | London | silver |
| 1002 | 1 | 2026-03-02 | Notebook | 4 | 120 | delivered | Asha Patel | [REDACTED] | Mumbai | gold |
| 1003 | 2 | 2026-03-03 | Water Bottle | 4 | 299 | delivered | Ben Carter | [REDACTED] | London | silver |
| 1004 | 4 | 2026-03-04 | Keyboard | 1 | 1599 | delivered | Dev Sharma | [REDACTED] | Delhi | bronze |

*…and 38 more rows*

If both tables have a column with the same name, the right one is renamed with `_right` so nothing is lost.

### Σ Summarise — "totals, counts, averages"

Collapses many rows into a few. Pick what to **group by** (one result row per value) and what to **calculate**.

| Calculation | Meaning |
|---|---|
| count rows | How many rows |
| count different values | How many *distinct* values |
| total (sum) · average · smallest · largest · median | Needs a **number** column |

Group by `city`, count rows:

| city | people |
|---|---|
| Delhi | 1 |
| Dubai | 1 |
| London | 1 |
| Mumbai | 1 |
| Rome | 1 |
| Unknown | 1 |

```sql
SELECT "city", count(*) AS "people"
FROM input
GROUP BY "city"
ORDER BY "city"
```

![Node settings and column chips](images/data-node-settings.png)

### ✅ Quality Check — "stop bad data early"

Bad data is the most common reason AI and reports go wrong, and the most expensive moment to find out is *after* the
numbers have reached someone. A **Quality Check** node sits between two steps and checks the table that flows through
it. If something is wrong the run **stops** (or just warns, your choice) and tells you exactly what and where.

| Check | Plain meaning | Example |
|---|---|---|
| Never empty | No blank / missing values | `customer_id` is always filled in |
| No duplicates | Every value (or combination) appears once | `order_id` |
| Number / date in range | Between a minimum and/or maximum | `quantity` between 1 and 100 |
| Only these values | A fixed list | `status` is `delivered`, `shipped` or `cancelled` |
| Matches a pattern | Text matches a regular expression | `order_date` looks like `2026-03-31` |
| At most N% empty | Tolerate a few blanks | `age` at most 5% empty |
| At least / at most N rows | Table size sanity check | "yesterday's load wasn't empty" |
| Columns match a contract | Required columns (and types) exist | `order_id` is an integer |
| Custom condition | Any SQL condition that must hold | `quantity * unit_price > 0` |

Each check is either **must pass** (can stop the run) or **warn only** (reported, never stops it). The node setting
**When a check fails** chooses between *Stop the run* and *Keep going, just report it*.

**Example — the dirty orders file** (*Sample: "Data: Quality gate on dirty orders"*). Five checks, all of which find a
real problem in `orders_dirty.csv`:

| | Check | Result |
|---|---|---|
| ❌ | order_id must be unique | 1 value(s) appear more than once |
| ❌ | customer_id, unit_price must not be empty | 2 of 16 rows break this rule |
| ❌ | quantity must be between 1 and 100 | 3 of 16 rows break this rule |
| ❌ | status must be one of: delivered, shipped, cancelled | 2 of 16 rows break this rule |
| ❌ | order_date must match ^\d{4}-\d{2}-\d{2}$ | 1 of 16 rows break this rule |

Click a failed check to see **example rows** that broke it (personal data masked as usual):

| order_id | customer_id | order_date | product | quantity | unit_price | status |
|---|---|---|---|---|---|---|
| 2004 | 4 | 2026-03-03 | Keyboard | -2 | 1599 | delivered |
| 2005 | 5 | 2026-03-04 | Water Bottle | 0 | 299 | cancelled |
| 2006 | 6 | 2026-03-04 | Notebook | 500 | 120 | delivered |

![Quality report](images/quality-report.png)

If the node is set to **Stop**, the run fails with a message you can act on, and nothing after the gate runs:

> *Node 'Order checks' failed: 5 of 5 quality checks did not pass — order_id must be unique (1 value(s) appear more than
> once); customer_id, unit_price must not be empty (2 of 16 rows break this rule); quantity must be between 1 and 100
> (3 of 16 rows break this rule); status must be one of: delivered, shipped, cancelled (2 of 16 rows break this rule)
> and 1 more*

The table passes through the gate **unchanged**, so you can put gates anywhere without copying data. All checks are
evaluated in **one pass** over the data (the SQL is shown in the preview, so you can see exactly how each check works).

**Don't know what to check? Let FlowMind suggest.** After **Preview data**, open the Quality Check node and click
**✨ Suggest checks from my data**. FlowMind profiles the table and proposes checks with plain reasons, which you can
untick before adding:

- The table should not be empty
- 'order_id' is never empty in this data
- every 'order_id' is different in this data
- 'customer_id' is never empty in this data
- 'product' only has these 6 values today
- 'quantity' currently ranges from 1 to 4 — widen if that's too tight
- 'unit_price' currently ranges from 120 to 2499 — widen if that's too tight
- 'status' only has these 3 values today

(That is the suggestion list for the clean `orders.csv`. They are *drafts*: "quantity currently ranges 1 to 4" is
suggested as a **warn-only** range so you can widen it if real data may go higher.)

![The check editor](images/quality-editor.png)

### 🧾 SQL — "for engineers (and the curious)"

See [Pro mode](#6-pro-mode-the-sql-node).

---

## 5. Tutorials

Each tutorial has a ready-made **Sample Workflow** — load it, press **Preview data**, and compare with the tables.

### Tutorial 1 — Tidy up messy contacts  *(Sample: "Data: Tidy up messy contacts")*

**Goal:** a clean list and a count of people per city.
**Steps:** Load `messy_contacts.csv` → **Clean** (settings above) → **Summarise** (group by `city`, count rows).
**Result:** the *People per city* table above — 6 people, one per city (including `Unknown`).
**What you learned:** nodes chain; every step's SQL is visible; sensitive columns are masked.

### Tutorial 2 — Sales by region  *(Sample: "Data: Sales by region")*

**Goal:** revenue and units per region from the daily sales file.
**Steps:** Load `sales.csv` → **Summarise** (group by `region`; total of `revenue`; total of `units`).
**Result:**

| region | total_revenue | total_units |
|---|---|---|
| East | 214861 | 221 |
| North | 253369 | 232 |
| South | 260327 | 248 |
| West | 229966 | 195 |

### Tutorial 3 — Join two tables  *(Sample: "Data: Orders + customers (join)")*

**Goal:** how much did each customer *tier* spend (ignoring cancelled orders)?
**Steps:** Load `orders.csv` and `customers.csv` → **Combine** (match `customer_id`) → **SQL**:

```sql
SELECT tier,
       count(*) AS orders,
       round(sum(quantity * unit_price), 2) AS revenue
FROM input
WHERE status <> 'cancelled'
GROUP BY tier
ORDER BY revenue DESC
```

**Result:**

| tier | orders | revenue |
|---|---|---|
| silver | 18 | 64958 |
| gold | 17 | 35717 |
| bronze | 4 | 6333 |

![Join preview](images/data-join-preview.png)

### Tutorial 4 — Stop bad data before it spreads  *(Sample: "Data: Quality gate on dirty orders")*

**Goal:** make sure the orders feed is trustworthy before totals are calculated.
**Steps:**
1. **Data → Profile** on `orders_dirty.csv` and notice the oddities (empty `customer_id`, `yesterday` as a date, `-2` quantity).
2. Load the sample, press **Preview data**. The Quality Check shows **5 of 5 checks failed** with example rows.
3. Click the **Order checks** node. The gate is on **Keep going, just report it** (so you can look around); switch it to
   **Stop the run**, press **Execute → Run Workflow**.
4. The run is marked **Failed** with the readable reason above, nothing after the gate ran, and **Runs** shows the
   [lineage](#8-lineage--where-did-this-number-come-from) with the failed checks.
5. Fix the source data (or relax a check that was too strict) and run again.

**What you learned:** a gate turns "wrong numbers in a dashboard" into "run stopped, here is why".

### Tutorial 5 — Share a table safely  *(Sample: "Data: Protect personal data")*

**Goal:** give a colleague or an AI a customer table without exposing personal data.
**Steps:** Load `customers.csv` → **Clean** with *Protect personal data* (email → hash, name → mask) → **SQL** to
select the columns you want to share. **Result:** the table in [Clean → Protect](#-clean--fix-the-mess).

### Tutorial 6 — Database → report

1. Add a PostgreSQL **Connection** and **Test** it.
2. **Load Data** → *A database table* → pick the table (optionally limit columns and rows).
3. Add **Clean** / **Summarise** as in the tutorials above.
4. **Preview data**, then **Execute**.

### Tutorial 7 — Run it every morning

1. Save the workflow.
2. Open **Runs → Schedules**, pick the workflow, choose *Every day at 09:00* and your timezone, press **Create**.
3. Each morning FlowMind runs it in the background; open **Runs** for status and **Data → Pipeline outputs** for the
   tables. See the [Phase 1 guide](phase1-foundation.md) for how schedules and retries behave.

---

## 6. Pro mode: the SQL node

If you know SQL, the **SQL** node lets you write one `SELECT` query over the tables connected to it.

**Table names you can use**

| Name | Refers to |
|---|---|
| `input` | The first connected node's table |
| `input2`, `input3`, … | The second, third… connected tables |
| a name from the node's label | e.g. a node labelled **Orders** can also be queried as `orders` |

(The node's settings panel lists the exact names for your canvas.)

**Example — best-selling delivered products** *(Sample: "Data: Top products (SQL)")*:

```sql
SELECT product,
       sum(quantity) AS units,
       sum(quantity * unit_price) AS revenue
FROM orders
WHERE status = 'delivered'
GROUP BY product
ORDER BY revenue DESC
LIMIT 5
```

| product | units | revenue |
|---|---|---|
| Headphones | 17 | 42483 |
| Keyboard | 10 | 15990 |
| Desk Lamp | 20 | 14980 |
| Backpack | 5 | 4450 |
| Water Bottle | 14 | 4186 |

**Rules (they keep your data and everyone else's safe):**

- **One `SELECT` statement.** `INSERT`, `DROP`, `COPY`, `ATTACH`, `PRAGMA`, `SET`, `INSTALL` are refused.
- **No files, no internet.** The query can only see the tables connected to it.
- The engine is **DuckDB**, so modern SQL works: window functions, `QUALIFY`, `date_trunc`, `strftime`, `string_agg`…
- A query is stopped after **60 seconds** or when it needs too much memory, and the message tells you what to try.

### A mini cookbook

**Orders per month**

```sql
SELECT strftime(CAST(order_date AS DATE), '%Y-%m') AS month,
       count(*) AS orders
FROM input
GROUP BY month
ORDER BY month
```

| month | orders |
|---|---|
| 2026-03 | 43 |

**Running total per customer** (window function)

```sql
SELECT order_id, customer_id, quantity * unit_price AS amount,
       sum(quantity * unit_price) OVER (PARTITION BY customer_id ORDER BY order_date) AS running_total
FROM input
WHERE customer_id = 1
ORDER BY order_date
```

| order_id | customer_id | amount | running_total |
|---|---|---|---|
| 1002 | 1 | 480 | 480 |
| 1005 | 1 | 890 | 1370 |
| 1018 | 1 | 4797 | 6167 |
| 1027 | 1 | 1498 | 7665 |
| 1034 | 1 | 240 | 7905 |

**Keep the newest row per customer** (de-duplicate by a key)

```sql
SELECT *
FROM input
QUALIFY row_number() OVER (PARTITION BY customer_id ORDER BY order_date DESC) = 1
```

**Share of total**

```sql
SELECT region, sum(revenue) AS revenue,
       round(100.0 * sum(revenue) / sum(sum(revenue)) OVER (), 1) AS pct
FROM input
GROUP BY region
```

---

## 7. How it works (the 60-second version)

```mermaid
flowchart LR
    P["Preview / Execute"] --> N["Node settings"]
    N -->|"Clean, Combine, Summarise<br/>are translated into"| SQL["one SQL query"]
    SQL --> E["Isolated DuckDB engine<br/>(own process, no internet,<br/>no files except your tables)"]
    E --> R["Result table<br/>(stored as Parquet)"]
    R --> NEXT["Next node"]
```

- **Simple nodes are SQL in disguise.** The *Clean*, *Combine* and *Summarise* nodes don't have their own engine;
  they write a SQL query for you. That is why the preview can show the SQL, and why you can "graduate" to the SQL
  node whenever you want more control.
- **Tables are passed by reference.** Between nodes, FlowMind passes a pointer to a file, not millions of rows. Only a
  small masked **sample** is shown in the browser.
- **Safe by design.** The engine runs in a separate process that is killed when it runs too long, can't touch the
  network or any file you didn't connect, and only ever sees *your* data.

---

## 8. Lineage — "where did this number come from?"

Every run that used data nodes keeps a **lineage record**: which file or table each step read, which table it
produced, how many rows, and whether its quality checks passed. Open **Runs**, expand a run, and look at **Data
lineage**:

![Lineage of a run](images/lineage-run.png)

For auditors, data catalogs and data engineers there is also the **OpenLineage JSON** download — the industry-standard
format understood by tools such as Marquez, DataHub and OpenMetadata. It lists every step as a standard *job run* with
its inputs, outputs, column list, row counts, the SQL it ran and its quality-check results. Admins can have FlowMind
send these events to a lineage server automatically (see the [technical reference](phase3-trust-and-lineage.md)).

---

## 9. Using results with the rest of FlowMind

A data node's output also works with the existing nodes: connect it to a **Rule**, **Switch**, **Formatter**, **AI
Agent** or **HTTP** node. They receive the table's schema and a small sample (`dataset.sample`) — handy for
"summarise these results with AI" or "post the totals to Slack". Large tables stay in storage; download them from
**Data → Pipeline outputs**.

---

## 10. Limits, costs and privacy

| Topic | Rule |
|---|---|
| **File size** | 25 MB per upload |
| **Storage** | 500 MB per account (uploads + saved outputs). The Data page shows your usage |
| **Rows** | Load Data reads up to 1,000,000 rows; a SQL result may have up to 1,000,000 rows |
| **Time** | A query is stopped after 60 seconds |
| **Preview** | Free; samples up to 1,000 rows; AI/HTTP/KYC/code nodes are skipped |
| **Credits (Execute)** | Load 1 · Clean 1 · Summarise 1 · **Quality Check 1** · Combine 2 · SQL 2. Plus **1 extra credit** for every full 100 MB scanned and for every full 30 s of compute — small data costs the base price |
| **Saved outputs** | Deleted automatically after 7 days (download what you want to keep). Uploaded files stay until you delete them |
| **Sensitive data** | Columns that look personal — by **name or by their values** — are masked in previews, results, quality-check examples and stored traces |
| **Lineage** | Kept as long as run history (30 days by default) |
| **Who can see what** | Your files and outputs are visible only to you. Admins can see that a connection exists (never its password) |

If you run out of credits, Execute stops **before** anything runs and tells you how many credits it needs. Preview
always works.

---

## 11. When something goes wrong

| You see | It usually means | Fix |
|---|---|---|
| *File 'x.csv' not found. Upload it on the Data page first.* | The file name in Load Data doesn't exist for your account | Upload it (or **Load example data**) and pick it in the node |
| *Column 'abc' was not found in the input. Available columns: …* | Typo, or an earlier node renamed/dropped it | Use the column chips; run **Preview data** to refresh them |
| *Cannot sum 'region': it is VARCHAR, not numbers.* | You asked for a total of a text column | Pick a number column, or convert it first with SQL: `CAST(col AS DOUBLE)` |
| *Cannot match 'a' (BIGINT) with 'b' (VARCHAR): the types differ.* | The two matching columns are different types (a number vs. text) | Convert one side first (SQL node: `CAST(...)`) |
| *Combine needs two inputs…* | Only one node is connected | Connect two data nodes; first = left, second = right |
| *… needs data: connect a Load Data node to its input* | The node has nothing feeding it | Draw a line from a data node into it |
| *Only SELECT queries are allowed…* | SQL node contains INSERT/DROP/COPY/… | Use a single `SELECT` |
| *Permission Error … file system operations are disabled* | The SQL tried to read a file | Load the file with **Load Data** and query `input` |
| *The query took longer than 60s…* | Too much data / expensive query | Filter or aggregate earlier, use *Max rows*, or sample first |
| *N of M quality checks did not pass — …* | A Quality Check found real problems (this is the gate doing its job) | Open **Preview data**, click the failed check to see example rows; fix the data, or relax/`warn only` the check |
| *… column 'x' was not found. Available columns: …* (in a check) | A check names a column that isn't in the table coming in | Pick the column from the chips; re-run **Preview data** |
| *… a range needs a number or date column* | Range check on a text column | Convert the column first (e.g. a SQL node with `CAST(col AS DATE)`) |
| *… invalid pattern* | The regular expression isn't valid | Check brackets/escapes; test it on a few values |
| *… the condition must be one SQL expression* | A custom condition contained `;` | Write one expression, e.g. `quantity * unit_price > 0` |
| *Storage limit reached* | 500 MB full | Delete files / old outputs on the Data page |
| *Insufficient credits* | Not enough credits for Execute | Ask your admin for a top-up. Preview is still free |
| *Host … is a private or reserved address. Ask an admin to allow-list it* | Your database is on a private network | An admin adds the host to the connection's allow-list |

---

## 12. Glossary

- **CSV** — a plain-text spreadsheet; one row per line, columns separated by commas.
- **Parquet** — a compact, fast file format for tables, popular in data engineering.
- **Dataset / table** — rows and columns of data.
- **Schema** — the list of columns and their types (text, number, date…).
- **Join** — matching rows of two tables on a shared column.
- **Group by / aggregate** — collapse rows into groups and calculate a value for each (sum, count, average).
- **PII** — personally identifiable information (email, phone, ID numbers…); masked in previews.
- **SQL** — the standard language for querying tables. **DuckDB** is the engine FlowMind uses to run it.
- **Pipeline** — a workflow whose nodes move and shape data.
- **Dry run / preview** — a free test on a sample.
- **Quality check / gate** — a node that tests a table against rules and can stop the run.
- **Contract (schema contract)** — a promise about which columns exist and their types.
- **Profile** — per-column statistics: empty values, distinct values, smallest, largest.
- **Hash** — a one-way fingerprint of a value; the same input always gives the same hash. **Salt** — a secret added so hashes can't be guessed.
- **Mask** — hide most of a value but keep a hint (`******atel`).
- **Lineage** — the record of what data a step read and what it produced.
- **OpenLineage** — an open standard format for lineage events, understood by many data tools.

---

### Where next?

- Technical details, security model, API and configuration: [phase2-data-engine.md](phase2-data-engine.md)
- Quality checks, PII detection, profiling and lineage internals: [phase3-trust-and-lineage.md](phase3-trust-and-lineage.md)
- Connections, background runs and schedules: [phase1-foundation.md](phase1-foundation.md)
- The full roadmap (quality gates, vectors/RAG, ML, warehouses): [data-engineering-platform.md](data-engineering-platform.md)
