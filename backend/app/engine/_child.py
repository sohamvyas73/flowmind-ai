"""Runs ONE SQL job inside a locked-down DuckDB. Executed as a separate process (python -I _child.py).

Protocol: JSON request on stdin; the last line of stdout is ``__FM_RESULT__<json>``.
Order matters: (1) load the declared input files into in-memory tables, (2) switch off every form of
external access and lock the configuration, (3) only then run the user's SQL. After step 2 the SQL can see
nothing but the input tables: no files, no network, no ATTACH/COPY/INSTALL/PRAGMA.
"""
import json
import os
import sys
import time

MARK = "\n__FM_RESULT__"


def _json_default(o):
    """SUM() of integers is a DECIMAL/HUGEINT in DuckDB: send whole numbers as ints and the rest as floats."""
    from decimal import Decimal
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    return str(o)


def _lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _ident(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def _reader(path: str, fmt: str) -> str:
    p = _lit(path)
    if fmt == "parquet":
        return f"read_parquet({p})"
    if fmt == "csv":
        return f"read_csv({p}, auto_detect=true, header=true)"
    if fmt == "tsv":
        return f"read_csv({p}, delim='\\t', auto_detect=true, header=true)"
    if fmt == "json":
        return f"read_json_auto({p}, format='array')"
    if fmt == "jsonl":
        return f"read_json_auto({p}, format='newline_delimited')"
    raise ValueError(f"Unsupported format: {fmt}")


def main() -> dict:
    import duckdb
    import pyarrow.parquet as pq

    req = json.loads(sys.stdin.read())
    t0 = time.time()
    tmp = req["temp_dir"]
    con = duckdb.connect(":memory:", config={
        "memory_limit": f"{int(req['memory_mb'])}MB",
        "threads": int(req.get("threads", 2)),
        "temp_directory": tmp,
        "home_directory": tmp,
        "max_temp_directory_size": "1GB",
    })

    scanned_rows = 0
    scanned_bytes = 0
    for inp in req["inputs"]:
        con.execute(f"CREATE TABLE {_ident(inp['alias'])} AS SELECT * FROM {_reader(inp['path'], inp['format'])}")
        scanned_rows += con.execute(f"SELECT count(*) FROM {_ident(inp['alias'])}").fetchone()[0]
        scanned_bytes += os.path.getsize(inp["path"])

    # ── lock down ────────────────────────────────────────────────────────────────
    con.execute("SET enable_external_access=false")
    con.execute("SET autoinstall_known_extensions=false")
    con.execute("SET autoload_known_extensions=false")
    con.execute("SET lock_configuration=true")

    stmts = con.extract_statements(req["sql"])
    if len(stmts) != 1:
        return {"ok": False, "error": "Write exactly one SELECT statement."}
    if stmts[0].type != duckdb.StatementType.SELECT:
        return {"ok": False, "error": "Only SELECT queries are allowed (no INSERT, COPY, ATTACH, PRAGMA, SET, ...)."}

    body = stmts[0].query.strip().rstrip(";")
    max_rows = int(req["max_rows"])
    cur = con.execute(f"SELECT * FROM ({body}) AS _fm LIMIT {max_rows + 1}")
    columns = [{"name": d[0], "type": str(d[1])} for d in cur.description]
    to_arrow = getattr(cur, "to_arrow_table", None) or cur.fetch_arrow_table  # name differs across DuckDB versions
    table = to_arrow()
    if table.num_rows > max_rows:
        return {"ok": False, "error": f"Result has more than {max_rows:,} rows. Add a filter, aggregate, or LIMIT."}

    pq.write_table(table, req["out_path"])
    sample = table.slice(0, int(req["sample_rows"])).to_pylist()
    return {
        "ok": True,
        "columns": columns,
        "row_count": table.num_rows,
        "sample": sample,
        "out_bytes": os.path.getsize(req["out_path"]),
        "scanned_rows": scanned_rows,
        "scanned_bytes": scanned_bytes,
        "compute_s": round(time.time() - t0, 3),
    }


if __name__ == "__main__":
    try:
        out = main()
    except BaseException as e:  # noqa: BLE001 - reported to the parent as a clean error
        out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    sys.__stdout__.write(MARK + json.dumps(out, default=_json_default))
    sys.__stdout__.flush()
