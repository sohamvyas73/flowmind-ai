import os
import tempfile

# Must be set before any `app` import: the engine is created at import time.
# TEST_DATABASE_URL=postgresql://... runs the suite against a real PostgreSQL (needed for queue locking tests);
# otherwise a throwaway SQLite file is used.
_pg = os.environ.get("TEST_DATABASE_URL")
if _pg:
    from sqlalchemy import create_engine, text as _text
    _e = create_engine(_pg)
    with _e.begin() as _c:
        _c.execute(_text("DROP SCHEMA public CASCADE"))
        _c.execute(_text("CREATE SCHEMA public"))
    _e.dispose()
    os.environ["DATABASE_URL"] = _pg
else:
    _db = os.path.join(tempfile.mkdtemp(prefix="fm_test_"), "test.db")
    os.environ["DATABASE_URL"] = f"sqlite:///{_db}"
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="fm_data_")
os.environ["WORKER_ENABLED"] = "false"      # tests drive workers/scheduler explicitly
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ["ADMIN_EMAIL"] = "admin@test.local"
os.environ["ADMIN_PASSWORD"] = "admin-pass-123"
os.environ["EXECUTION_RETENTION_DAYS"] = "30"

# The models use PostgreSQL UUID columns; teach SQLite how to store them for tests.
from sqlalchemy.dialects.postgresql import UUID as _PGUUID
from sqlalchemy.ext.compiler import compiles


@compiles(_PGUUID, "sqlite")
def _uuid_on_sqlite(type_, compiler, **kw):
    return "CHAR(32)"
