import os
from unittest import TestCase, skipUnless

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, engine

IS_PG = engine.dialect.name == "postgresql"

# Schema as shipped before the auth / secrets / jobs work (users + workflows + executions only).
LEGACY_DDL = [
    "CREATE TYPE userrole AS ENUM ('USER','ADMIN')",
    "CREATE TYPE workflowstatus AS ENUM ('DRAFT','ACTIVE','PAUSED','ARCHIVED')",
    "CREATE TYPE executionstatus AS ENUM ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')",
    """CREATE TABLE users (
        id uuid PRIMARY KEY, email varchar(255) NOT NULL UNIQUE, hashed_password varchar(255) NOT NULL,
        full_name varchar(255), role userrole NOT NULL, api_token varchar(64) NOT NULL UNIQUE,
        credits_total integer NOT NULL, credits_used integer NOT NULL, is_active boolean NOT NULL,
        openai_api_key varchar(255), openai_model varchar(100), anthropic_api_key varchar(255),
        anthropic_model varchar(100), gemini_api_key varchar(255), gemini_model varchar(100),
        created_at timestamp, updated_at timestamp)""",
    """CREATE TABLE platform_settings (
        id integer PRIMARY KEY, openai_api_key varchar(255), openai_model varchar(100),
        anthropic_api_key varchar(255), anthropic_model varchar(100), gemini_api_key varchar(255),
        gemini_model varchar(100), updated_at timestamp)""",
    """CREATE TABLE workflows (
        id uuid PRIMARY KEY, user_id uuid, name varchar(255) NOT NULL, description text,
        graph_data json NOT NULL, status workflowstatus, created_at timestamp, updated_at timestamp, version varchar(50))""",
    """CREATE TABLE workflow_executions (
        id uuid PRIMARY KEY, workflow_id uuid NOT NULL, status executionstatus, input_data json,
        output_data json, execution_trace json, error_message text, started_at timestamp, completed_at timestamp)""",
    "INSERT INTO users VALUES ('11111111-1111-1111-1111-111111111111','old@x.com','h',NULL,'USER',"
    "'%s',100,5,true,'sk-old',NULL,NULL,NULL,NULL,NULL,now(),now())" % ("e" * 64),
    "INSERT INTO workflow_executions (id, workflow_id, status) VALUES "
    "('22222222-2222-2222-2222-222222222222','33333333-3333-3333-3333-333333333333','COMPLETED')",
]


@skipUnless(IS_PG, "schema upgrade test needs PostgreSQL (set TEST_DATABASE_URL)")
class LegacySchemaUpgradeTests(TestCase):
    def test_existing_database_upgrades_in_place_and_is_idempotent(self):
        base_url = os.environ["TEST_DATABASE_URL"]
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as c:
            c.execute(text("DROP DATABASE IF EXISTS flowmind_legacy"))
            c.execute(text("CREATE DATABASE flowmind_legacy"))
        legacy = create_engine(base_url.rsplit("/", 1)[0] + "/flowmind_legacy")
        try:
            with legacy.begin() as c:
                for stmt in LEGACY_DDL:
                    c.execute(text(stmt))

            # same order as app startup: create missing tables, then idempotent column migrations
            import app.main as main
            Base.metadata.create_all(bind=legacy)
            main.run_migrations(legacy)
            main.run_migrations(legacy)         # running twice must be harmless

            insp = inspect(legacy)
            self.assertTrue({"jobs", "schedules", "connections"} <= set(insp.get_table_names()))
            ucols = {c["name"]: c for c in insp.get_columns("users")}
            for col in ("api_token_hash", "api_token_prefix", "api_token_created_at"):
                self.assertIn(col, ucols)
            self.assertTrue(ucols["api_token"]["nullable"])                       # plaintext column can be emptied
            self.assertEqual(str(ucols["openai_api_key"]["type"]), "TEXT")        # room for ciphertext
            ecols = {c["name"]: c for c in insp.get_columns("workflow_executions")}
            for col in ("triggered_by", "schedule_id", "billed_user_id", "reserved_credits"):
                self.assertIn(col, ecols)
            self.assertIn("secrets", [c["name"] for c in insp.get_columns("workflows")])

            # existing rows get sane defaults and every ORM model can query the upgraded tables
            from app.models.user import User
            from app.models.workflow import WorkflowExecution
            Session = sessionmaker(bind=legacy)
            with Session() as s:
                ex = s.query(WorkflowExecution).first()
                self.assertEqual((ex.triggered_by, ex.reserved_credits), ("manual", 0))
                self.assertEqual(s.query(User).first().credits_used, 5)
        finally:
            legacy.dispose()
            with admin.connect() as c:
                c.execute(text("DROP DATABASE IF EXISTS flowmind_legacy"))
            admin.dispose()
