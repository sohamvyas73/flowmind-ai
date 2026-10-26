import asyncio
import os
import tempfile
import time
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from app.core.config import settings
from app.engine.duckdb_engine import EngineError, EngineInput, run_sql

CSV = "id,name,amt,email\n1,Ann,10,ann@x.com\n2,Bob,20,bob@x.com\n3,Cy,,cy@x.com\n"


class EngineTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fm_t_")
        with open(f"{self.d}/a.csv", "w") as f:
            f.write(CSV)
        self.inp = [EngineInput("sales", f"{self.d}/a.csv", "csv")]
        self.out = f"{self.d}/out.parquet"

    async def test_select_returns_schema_sample_and_parquet(self):
        r = await run_sql(self.inp, "SELECT name, amt * 2 AS dbl FROM sales WHERE amt IS NOT NULL ORDER BY id", self.out)
        self.assertEqual([c["name"] for c in r.columns], ["name", "dbl"])
        self.assertEqual(r.sample, [{"name": "Ann", "dbl": 20}, {"name": "Bob", "dbl": 40}])
        self.assertEqual((r.row_count, r.scanned_rows), (2, 3))
        self.assertTrue(os.path.getsize(self.out) > 0 and r.out_bytes == os.path.getsize(self.out))

    async def test_every_escape_attempt_is_blocked(self):
        attacks = [
            "SELECT * FROM read_csv('/etc/passwd')", "SELECT * FROM read_text('/etc/hostname')",
            "SELECT * FROM glob('/*')", "COPY sales TO '/tmp/fm_exfil.csv'", "ATTACH '/tmp/fm_y.db'",
            "INSTALL httpfs", "LOAD httpfs", "PRAGMA database_list", "SET enable_external_access=true",
            "DROP TABLE sales", "INSERT INTO sales VALUES (9,'x',1,'y')", "CREATE TABLE z AS SELECT 1",
            "SELECT 1; SELECT 2", "", "   ",
            "SELECT * FROM read_parquet('/etc/shadow')", "SELECT * FROM 'https://example.com/x.csv'",
        ]
        for sql in attacks:
            with self.assertRaises(EngineError, msg=sql):
                await run_sql(self.inp, sql, self.out)
        self.assertFalse(os.path.exists("/tmp/fm_exfil.csv"))
        self.assertFalse(os.path.exists(self.out))                     # nothing written for rejected queries

    async def test_cannot_see_files_outside_declared_inputs(self):
        other = f"{self.d}/secret.csv"
        with open(other, "w") as f:
            f.write("k\nv\n")
        with self.assertRaises(EngineError):
            await run_sql(self.inp, f"SELECT * FROM read_csv('{other}')", self.out)

    async def test_runaway_query_is_killed(self):
        t0 = time.time()
        with self.assertRaises(EngineError) as ctx:
            await run_sql(self.inp, "SELECT count(*) FROM range(100000000000) a, range(100000) b", self.out, timeout_s=2)
        self.assertLess(time.time() - t0, 10)
        self.assertIn("stopped", str(ctx.exception).lower())

    async def test_row_cap(self):
        with self.assertRaises(EngineError) as ctx:
            await run_sql(self.inp, "SELECT * FROM range(1000)", self.out, max_rows=100)
        self.assertIn("more than 100", str(ctx.exception))

    async def test_memory_limit_contains_a_memory_bomb(self):
        with patch.object(settings, "ENGINE_MEMORY_MB", 64):
            with self.assertRaises(EngineError):
                await run_sql(self.inp, "SELECT list(i) FROM range(500000000) t(i)", self.out, timeout_s=30)

    async def test_errors_are_readable_and_do_not_leak_paths(self):
        with self.assertRaises(EngineError) as ctx:
            await run_sql(self.inp, "SELECT nope FROM sales", self.out)
        msg = str(ctx.exception)
        self.assertIn("nope", msg)
        self.assertNotIn(self.d, msg)

    async def test_bad_aliases_and_duplicates(self):
        with self.assertRaises(EngineError):
            await run_sql([EngineInput("bad name", f"{self.d}/a.csv", "csv")], "SELECT 1", self.out)
        with self.assertRaises(EngineError):
            await run_sql(self.inp + [EngineInput("SALES", f"{self.d}/a.csv", "csv")], "SELECT 1", self.out)

    async def test_formats(self):
        with open(f"{self.d}/a.jsonl", "w") as f:
            f.write('{"a":1,"b":"x"}\n{"a":2,"b":"y"}\n')
        with open(f"{self.d}/a.json", "w") as f:
            f.write('[{"a":1},{"a":2},{"a":3}]')
        with open(f"{self.d}/a.tsv", "w") as f:
            f.write("a\tb\n1\tx\n2\ty\n")
        for name, fmt, n in (("a.jsonl", "jsonl", 2), ("a.json", "json", 3), ("a.tsv", "tsv", 2)):
            r = await run_sql([EngineInput("t", f"{self.d}/{name}", fmt)], "SELECT * FROM t", self.out)
            self.assertEqual(r.row_count, n, fmt)
        # parquet round trip
        r = await run_sql(self.inp, "SELECT * FROM sales", self.out)
        again = await run_sql([EngineInput("p", self.out, "parquet")], "SELECT count(*) AS n FROM p", f"{self.d}/o2.parquet")
        self.assertEqual(again.sample, [{"n": 3}])

    async def test_concurrent_jobs_are_serialised_not_broken(self):
        results = await asyncio.gather(*[
            run_sql(self.inp, "SELECT count(*) AS n FROM sales", f"{self.d}/c{i}.parquet") for i in range(5)
        ])
        self.assertTrue(all(r.sample == [{"n": 3}] for r in results))
