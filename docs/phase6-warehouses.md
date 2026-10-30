# Phase 6 — Warehouses and pushdown (technical reference)

Beginners: read the [warehouse guide](warehouse-guide.md).

## Idea

`Simple` data nodes already compile their settings to one SQL `SELECT` (Phase 2). Pushdown reuses those compilers:

1. A **Load Data** node with *Run on = In my warehouse* returns a **relation** — `SELECT … FROM schema.table` in the warehouse's
   dialect — plus a masked 100-row sample and the schema. No rows are copied; no `Dataset` row / Parquet file exists.
2. A following Clean / Combine / Summarise node compiles to DuckDB-flavoured SQL, then `sqlglot` qualifies it against the known
   columns (so `SELECT *`, `* REPLACE`, `DISTINCT *` become explicit column lists) and translates it to the warehouse's dialect.
   The upstream relation is attached as a uniquely named CTE (`fm_<id>_input`) with the original name kept as the table alias.
3. The **SQL** node takes the user's *native* SQL, renames its table references the same way, and validates the result.
4. Every step runs `SELECT * FROM (<relation>) LIMIT 100` for the sample; types come back in DuckDB-style names so later steps compile.
5. **Pull** materialises a relation into Parquet inside FlowMind (capped). **Save to Warehouse** writes a relation back with
   `CREATE TABLE … AS`, or a FlowMind table with batched inserts (PostgreSQL / ClickHouse only).

```
Load(warehouse) → Clean → Combine → Summarise ──► sample + schema        (data stays)
                                         └──► Pull ──► Parquet ──► Quality / AI / ML
                                         └──► Save ──► CREATE TABLE AS in the warehouse
```

## Components

| Module | Role |
|---|---|
| `app/warehouse/base.py` | `Warehouse` contract, `assert_select_only` guard, canonical type mapping, text-value decoding, quoting, rows→Parquet |
| `app/warehouse/clickhouse.py` | ClickHouse over HTTP (`readonly=1` for reads, JSONCompact, JSONEachRow inserts) |
| `app/warehouse/postgres.py` | PostgreSQL + Redshift via psycopg2, reusing the address-pinned, SSRF-safe connect |
| `app/warehouse/rest.py` | Databricks SQL Statement API, Snowflake SQL API v2, BigQuery `jobs.query` (+ service-account JWT exchange) |
| `app/connectors/warehouse.py` | Connection types `redshift clickhouse snowflake bigquery databricks` (test, browse, preview) |
| `app/services/pushdown.py` | Load/Step/Pull/Write, transpilation, relation naming, column-case alignment, lineage identities |
| `app/api/warehouse.py` | `GET /warehouse/types`, `POST /warehouse/connections/{id}/examples` |

## Nodes and settings

* **Load Data** (`loadDataNode`): `source=connection`, `connectionId`, `schema`, `table`, `columns[]`, `maxRows`, **`runOn`**
  (`warehouse` | `flowmind`). `runOn` is required for every warehouse except PostgreSQL, which keeps its original
  copy-rows default.
* **Pull to FlowMind** (`pullDataNode`): `maxRows`. Refuses inputs that are already in FlowMind.
* **Save to Warehouse** (`writeWarehouseNode`): `connectionId` (read-write), `schema`, `table`, **`mode`** (`create|replace|append`,
  required). Output is a relation on the written table, `written{table,mode,rows,how}`.
* Connection option `write_schema`: Save refuses any other schema.

Quality Check, Drift Check, Batch Score, Feedback and the AI nodes need rows; given a warehouse relation they fail with
*"This table lives in your warehouse… add a Pull node first"*.

## Safety model

* `Warehouse.query()` → `assert_select_only()`: exactly one statement, root `SELECT`/set-operation, no DDL/DML/`Command`/`Set`/
  transaction nodes anywhere in the tree, no `SELECT … INTO`, no table functions, and a deny-list of file/network/side-effect
  functions across dialects. Server-side: ClickHouse `readonly=1`; PostgreSQL read-only session.
* `Warehouse.write_table()` needs `access_mode=read_write` and only runs statements FlowMind generated. Identifiers are validated
  (`^[A-Za-z_][A-Za-z0-9_]{0,127}$`), system schemas refused, quoting escapes embedded quotes.
* REST adapters send tokens only in the `Authorization` header and use the SSRF-safe client; Snowflake/Databricks hosts are
  forced to `https://`.
* Sample rows go through the same PII detection/redaction as every `DatasetRef`.

## Dialect notes

* SHA-256 for *Protect → hash* is rendered per dialect (hex, lower-case) so hashes equal DuckDB's:
  ClickHouse `lower(hex(SHA256(x)))`, PostgreSQL `encode(sha256(convert_to(x,'UTF8')),'hex')`, Snowflake/Databricks/Redshift `sha2(x,256)`,
  BigQuery `LOWER(TO_HEX(SHA256(x)))`.
* Types: native → `BIGINT/DOUBLE/DECIMAL/BOOLEAN/DATE/TIMESTAMP/VARCHAR`. The REST APIs return text; values are decoded
  (Snowflake dates are days since epoch and timestamps epoch seconds; BigQuery timestamps are epoch seconds; Databricks inline results
  are limited to ~25 MB).
* Snowflake reports upper-case column names; typed column names are matched case-insensitively, and bare table/column names in
  Load are left unquoted so the warehouse applies its own case rules.

## Lineage and billing

Lineage events carry OpenLineage-style identities (`clickhouse://host:8123` / `db.table`, `postgres://host:port` / `db.schema.table`,
`snowflake://account`, `bigquery` / `project.dataset.table`, `databricks://host`). Pushdown steps are 1 credit (Combine/SQL 2), Pull 1,
Save 2 — flat; the warehouse bills its own compute. Failed steps are not billed.

## Verification — what the tests prove, and what they don't

`tests/test_warehouse.py` (74 tests) + `tests/test_warehouse_rest.py` (107 tests):

* **Real engines — ClickHouse 24.8 and PostgreSQL 16:** the same Summarise / Clean / Protect / Join / native-SQL pipelines are run
  inside FlowMind (DuckDB) and pushed down, and the answers compared. Also: connection test, browse, preview, copy-in mode,
  Pull → Quality Check, Save create/append/replace, FlowMind→warehouse inserts, system-schema and `write_schema` guard-rails,
  read-only enforcement by the server, injection attempts in table/column names, billing, lineage, tenancy.
* **Snowflake, BigQuery, Databricks — simulators:** each simulator speaks the vendor's documented wire format (JSON shapes, text-encoded
  values, async polling, result partitions/pages, auth headers, service-account token exchange) and executes the received SQL in DuckDB.
  The full suite runs through each. This verifies *FlowMind's side* — requests, decoding, pushdown, safety — not the real services.
* **Redshift:** PostgreSQL wire protocol; tested against PostgreSQL, SQL generated with the `redshift` dialect.

**Not verified:** any live Snowflake / BigQuery / Databricks / Redshift account; key-pair (JWT) auth for Snowflake (tokens only);
very large results from Databricks (>25 MB inline) and Snowflake multi-partition pulls beyond the simulator; warehouse-specific
quirks such as Snowflake quoted-identifier edge cases; `docker compose up` for the demo ClickHouse (validated with `docker compose config`;
the same image was run by hand).

## Not in this phase

Quality checks and Drift Check inside the warehouse; dbt / Spark / Airflow nodes; the customer runner (Phase 7); Snowflake key-pair auth,
BigQuery storage-API / large-result pulls, Databricks external links; writing a FlowMind table into Snowflake/BigQuery/Databricks.
