# Warehouses and "pushdown" — a beginner-friendly guide

Many teams already keep their data in a **warehouse** (ClickHouse, Snowflake, BigQuery, Databricks, Redshift, or just
PostgreSQL). Copying that data into FlowMind to work on it is slow, costs money and creates a second copy of private data.

**Pushdown** means the opposite: *FlowMind sends the question to your warehouse, the warehouse does the work, and only a
small sample comes back.* Your data stays where it is.

```
  your warehouse ── (data never moves) ──────────────┐
        ▲                                            │
        │  FlowMind writes the SQL for you           │
        │  (Clean, Combine, Summarise, or your own)  ▼
   FlowMind ◄──── a 100-row, privacy-masked sample + the column names
```

> **Nothing is chosen for you.** You pick the connection, and you pick *where each Load runs*. Writing a table back needs a
> "Read & write" connection and an explicit choice of what to do if the table exists.

---

## 1. Connect your warehouse (once)

**Connections** page → *New connection*.

| Type | What you give it | How well it has been tested here |
|---|---|---|
| **ClickHouse** | HTTP URL, user, password, database | ✅ real ClickHouse 24.8 server |
| **PostgreSQL** | host, database, user, password | ✅ real PostgreSQL 16 server |
| **Amazon Redshift** | host (port 5439), database, user, password | ◐ same wire protocol as PostgreSQL (tested there) — not a real Redshift cluster |
| **Snowflake** | account, access token, warehouse, database | ◐ simulator of the SQL API — not a real account |
| **Google BigQuery** | project, service-account key (or token), dataset | ◐ simulator of the REST API — not a real project |
| **Databricks SQL** | workspace host, SQL warehouse ID, access token | ◐ simulator of the SQL Statement API — not a real workspace |

![New ClickHouse connection](images/gallery/12-warehouses/07-new-clickhouse-connection.png)
![New Snowflake connection](images/gallery/12-warehouses/08-new-snowflake-connection.png)

*Local servers need an admin to allow-list the host.* Credentials are encrypted and never shown again. Connections are
**read-only by default**.

**No warehouse yet? Start a demo ClickHouse** (one command), or point at any PostgreSQL:

```bash
./scripts/warehouses.sh start clickhouse        # http://localhost:8123 · user flowmind · password flowmind-demo · database shop
```

Add a ClickHouse connection (access **Read & write**), then press **Load example tables** on its card. FlowMind creates
`customers`, `orders`, `sales` and the other example tables so you can follow every example below.

![Warehouse connections](images/gallery/12-warehouses/01-warehouse-connections.png)

---

## 2. Leave the data in the warehouse

Add **Load Data** → *A database table* → pick the connection and table → **Where should the work run? → In my warehouse**.
Then add normal **Clean / Combine / Summarise / SQL** nodes after it.

Sample **Warehouse: Revenue by region (data stays put)**: *Load `sales` → Summarise (sum of revenue by region)*.

![Pushdown summarise](images/gallery/12-warehouses/02-pushdown-summarise.png)

What FlowMind actually sent to ClickHouse:

```sql
WITH "fm_cce5e2f9_input" AS (SELECT * FROM shop.sales)
SELECT "input"."region" AS "region", SUM("input"."revenue") AS "total_revenue",
       SUM("input"."units") AS "total_units", COUNT(*) AS "days"
FROM "fm_cce5e2f9_input" AS "input" GROUP BY "input"."region" ORDER BY "region"
```

and the answer (the only thing that came back):

| region | total_revenue | total_units | days |
|---|---|---|---|
| East | 214,861 | 221 | 14 |
| North | 253,369 | 232 | 14 |
| South | 260,327 | 248 | 14 |
| West | 229,966 | 195 | 14 |

The **same** pipeline on the CSV inside FlowMind gives identical numbers — the test-suite checks that for Clean, Combine,
Summarise, SQL and personal-data protection on every engine.

### Join two warehouse tables, still in place

![Pushdown join](images/gallery/12-warehouses/03-pushdown-join.png)

**Preview data** shows the exact SQL each step runs in your warehouse:

![Preview with warehouse SQL](images/gallery/12-warehouses/06-preview-warehouse-sql.png)

### Your own SQL, in your warehouse's language
The **SQL** node, when its input lives in a warehouse, is written in *that warehouse's* SQL (ClickHouse SQL, Snowflake SQL,
…). Use `input` (and `input2`, …) as the table names. Only a single `SELECT` is allowed — see *Safety* below.

### What you will notice
* Row counts are not shown ("in your warehouse"): counting a huge table is itself a costly query, so FlowMind only asks for
  a 100-row sample and the column names.
* Personal data (emails, phone numbers, …) in that sample is masked, exactly as for files.
* **Preview** limits the source table to the first rows, so it is cheap on your warehouse bill. A real run does not.
* **Snowflake** reports column names in UPPER CASE; type `region` or `REGION` — FlowMind matches them ignoring case.

---

## 3. Bring a table into FlowMind (when you need the rows)

Some steps need the actual rows: **Quality Check**, **AI**, **ML scoring**, **Drift Check**. Put a **Pull to FlowMind** node
in front of them. Do the heavy work in the warehouse first, so only the small result comes in:

![Pull and quality check](images/gallery/12-warehouses/04-pull-and-quality-check.png)

Here 56 daily rows were summarised *in ClickHouse* and only **4 rows** were pulled. Limit: 1,000,000 rows (100,000 by default
in the sample); a node tells you if it stopped at the limit. If you try Quality Check straight on a warehouse table you get
a clear message telling you to add a Pull node.

---

## 4. Save a result back as a table

**Save to Warehouse** writes the connected table into your warehouse:

![Save to warehouse](images/gallery/12-warehouses/05-save-to-warehouse.png)

* You must choose **what happens if the table exists**: *create new (fail if it exists)*, *append*, or *replace*.
  Nothing is chosen for you; *replace* drops the old table first.
* The connection must be **Read & write**.
* If the table came from the same warehouse, the table is created *inside* the warehouse (`CREATE TABLE … AS SELECT …`) —
  no data leaves it.
* A table that lives in FlowMind can be copied into PostgreSQL or ClickHouse (up to 200,000 rows). The other warehouses
  don't support that yet — keep the data in the warehouse instead.
* Guard-rails: system schemas (`information_schema`, `system`, …) are refused; table names are validated; and a connection
  can have **"Only allow writing to this schema"** (for example `flowmind`) so an automated pipeline cannot touch your
  production tables.
* The result continues down the pipeline as a table in the warehouse.

---

## Safety, in plain words

* **Reading is read-only.** Every query FlowMind sends must be a single `SELECT`. `DROP`, `DELETE`, `INSERT`, several
  statements at once, `SELECT … INTO`, and functions that read files or call other servers (`url()`, `file()`, `s3()`,
  `remote()`, `dblink()`, `pg_read_file()`, `pg_sleep()` …) are refused before they leave FlowMind. ClickHouse and PostgreSQL
  are additionally told to run the session read-only.
* **Writes only come from the Save node**, using statements FlowMind generates itself, never typed SQL.
* Credentials are encrypted; private addresses need an admin allow-list; errors never echo passwords or tokens.
* Give FlowMind a **warehouse user with only the access it needs** (read on the schemas it should see, write on one schema).
  That is the strongest protection of all, and is the vendor's own permission system doing its job.

## What it costs
Pushdown nodes cost a flat 1 credit each (Combine/SQL 2, Save 2, Pull 1), whatever the size of your warehouse. **Your
warehouse bills its own compute** — a pipeline of five steps over a big table runs those five steps there.

## Common questions

**Why can't Quality Check run in the warehouse?** It needs the rows. Pull a (small) table first. Running checks inside the
warehouse is on the list for later.

**Can I mix a warehouse table and a file?** Not in one Combine: use Pull to bring the warehouse table in, or Save the file
into the warehouse first.

**Which SQL features work in Clean / Summarise?** The ones the nodes offer (trim, case, fill, hash/mask, duplicates, join,
sum/avg/min/max/median/count/distinct count). FlowMind translates them to each warehouse's dialect and tells you if a step
cannot be translated.
