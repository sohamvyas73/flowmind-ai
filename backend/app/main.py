import asyncio
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.core.config import settings
from app.core.database import Base, engine, SessionLocal
from app.api import workflows
from app.api import auth as auth_router
from app.api import admin as admin_router
from app.api import config as config_router
from app.api import connections as connections_router
from app.api import data as data_router
from app.api import lineage as lineage_router
from app.api import runs as runs_router
from app.api import schedules as schedules_router
from app.core import maintenance

# Register all models with Base before create_all
from app.models import workflow as _wf_models  # noqa: F401
from app.models import user as _user_models    # noqa: F401
from app.models import job as _job_models      # noqa: F401
from app.models import schedule as _schedule_models  # noqa: F401
from app.models import connection as _connection_models  # noqa: F401
from app.models import data as _data_models    # noqa: F401
from app.models import lineage as _lineage_models  # noqa: F401

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Create all tables (new tables; existing ones untouched)
Base.metadata.create_all(bind=engine)

# Idempotent migrations for columns added after initial release
_MIGRATIONS = [
    "ALTER TABLE workflows ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS openai_api_key VARCHAR(255);",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS openai_model VARCHAR(100);",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS anthropic_api_key VARCHAR(255);",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS anthropic_model VARCHAR(100);",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS gemini_api_key VARCHAR(255);",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS gemini_model VARCHAR(100);",
    # Secrets hardening: hashed API tokens, encrypted provider keys, node-secret vault
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS api_token_hash VARCHAR(64);",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS api_token_prefix VARCHAR(12);",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS api_token_created_at TIMESTAMP;",
    "ALTER TABLE users ALTER COLUMN api_token DROP NOT NULL;",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_api_token_hash ON users (api_token_hash);",
    "ALTER TABLE users ALTER COLUMN openai_api_key TYPE TEXT;",
    "ALTER TABLE users ALTER COLUMN anthropic_api_key TYPE TEXT;",
    "ALTER TABLE users ALTER COLUMN gemini_api_key TYPE TEXT;",
    "ALTER TABLE platform_settings ALTER COLUMN openai_api_key TYPE TEXT;",
    "ALTER TABLE platform_settings ALTER COLUMN anthropic_api_key TYPE TEXT;",
    "ALTER TABLE platform_settings ALTER COLUMN gemini_api_key TYPE TEXT;",
    "ALTER TABLE workflows ADD COLUMN IF NOT EXISTS secrets TEXT;",
    # Phase 1: async runs
    "ALTER TABLE workflow_executions ADD COLUMN IF NOT EXISTS triggered_by VARCHAR(20) NOT NULL DEFAULT 'manual';",
    "ALTER TABLE workflow_executions ADD COLUMN IF NOT EXISTS schedule_id UUID;",
    "ALTER TABLE workflow_executions ADD COLUMN IF NOT EXISTS billed_user_id UUID;",
    "ALTER TABLE workflow_executions ADD COLUMN IF NOT EXISTS reserved_credits INTEGER NOT NULL DEFAULT 0;",
]

def run_migrations(target_engine=engine) -> None:
    for _sql in _MIGRATIONS:
        try:
            with target_engine.connect() as conn:
                conn.execute(text(_sql))
                conn.commit()
        except Exception as e:
            logger.warning("Migration skipped: %s | %s", _sql[:60], e)


run_migrations()


def _seed_admin():
    from app.models.user import User, UserRole
    from app.core.auth import hash_password, generate_api_token, set_api_token

    admin_email = getattr(settings, "ADMIN_EMAIL", None)
    admin_password = getattr(settings, "ADMIN_PASSWORD", None)
    if not admin_email or not admin_password:
        return

    db = SessionLocal()
    try:
        if not db.query(User).filter(User.email == admin_email).first():
            admin_user = User(
                email=admin_email,
                hashed_password=hash_password(admin_password),
                full_name="Admin",
                role=UserRole.ADMIN,
                credits_total=999_999,
                is_active=True,
            )
            set_api_token(admin_user, generate_api_token())
            db.add(admin_user)
            db.commit()
            logger.info("Admin user created: %s", admin_email)
        else:
            # Ensure existing admin is active
            admin = db.query(User).filter(User.email == admin_email).first()
            if admin and not admin.is_active:
                admin.is_active = True
                db.commit()
    finally:
        db.close()

maintenance.migrate_secrets()
_seed_admin()

if settings.SECRET_KEY == "your-secret-key-change-in-production":
    logger.warning("SECRET_KEY is the insecure default — set a strong SECRET_KEY (also used to encrypt stored keys unless ENCRYPTION_KEY is set)")


def _warn_disabled_code_nodes():
    """Tell operators which saved workflows contain a Code Runner node that is now skipped."""
    if settings.ENABLE_CODE_NODE:
        return
    from app.models.workflow import Workflow
    db = SessionLocal()
    try:
        affected = [
            w.name for w in db.query(Workflow).all()
            if any(n.get("type") == "codeNode" for n in (w.graph_data or {}).get("nodes", []))
        ]
        if affected:
            logger.warning(
                "ENABLE_CODE_NODE=false: %d saved workflow(s) contain a Code Runner node that will be skipped: %s",
                len(affected), ", ".join(affected[:20]),
            )
    except Exception as e:
        logger.warning("Code node audit skipped: %s", e)
    finally:
        db.close()


_warn_disabled_code_nodes()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router,   prefix=f"{settings.API_V1_STR}/auth",      tags=["auth"])
app.include_router(admin_router.router,  prefix=f"{settings.API_V1_STR}/admin",     tags=["admin"])
app.include_router(config_router.router, prefix=f"{settings.API_V1_STR}/config",    tags=["config"])
app.include_router(connections_router.router, prefix=f"{settings.API_V1_STR}/connections", tags=["connections"])
app.include_router(data_router.router,      prefix=f"{settings.API_V1_STR}/data",        tags=["data"])
app.include_router(lineage_router.router,  prefix=f"{settings.API_V1_STR}/lineage",     tags=["lineage"])
app.include_router(runs_router.router,      prefix=f"{settings.API_V1_STR}/runs",        tags=["runs"])
app.include_router(schedules_router.router, prefix=f"{settings.API_V1_STR}/schedules",   tags=["schedules"])
app.include_router(workflows.router,     prefix=f"{settings.API_V1_STR}/workflows", tags=["workflows"])


@app.on_event("startup")
async def _start_background() -> None:
    from app.jobs.runtime import run_background

    app.state.retention_task = asyncio.create_task(maintenance.retention_loop())
    app.state.stop_event = asyncio.Event()
    if settings.WORKER_ENABLED or settings.SCHEDULER_ENABLED:
        app.state.background_task = asyncio.create_task(
            run_background(app.state.stop_event, worker=settings.WORKER_ENABLED, sched=settings.SCHEDULER_ENABLED)
        )


@app.on_event("shutdown")
async def _stop_background() -> None:
    app.state.stop_event.set()
    task = getattr(app.state, "background_task", None)
    if task:
        try:
            await asyncio.wait_for(task, timeout=35)
        except Exception:
            task.cancel()
    app.state.retention_task.cancel()


@app.get("/")
async def root():
    return {"message": "AI Workflow Platform API", "version": settings.VERSION}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
