import os
import tempfile

# Must be set before any `app` import: the engine is created at import time.
_db = os.path.join(tempfile.mkdtemp(prefix="fm_test_"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db}"
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
