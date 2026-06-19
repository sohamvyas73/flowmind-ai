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

# Register all models with Base before create_all
from app.models import workflow as _wf_models  # noqa: F401
from app.models import user as _user_models    # noqa: F401

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
]

for _sql in _MIGRATIONS:
    try:
        with engine.connect() as conn:
            conn.execute(text(_sql))
            conn.commit()
    except Exception as e:
        logger.warning("Migration skipped: %s | %s", _sql[:60], e)


def _seed_admin():
    from app.models.user import User, UserRole
    from app.core.auth import hash_password, generate_api_token

    admin_email = getattr(settings, "ADMIN_EMAIL", None)
    admin_password = getattr(settings, "ADMIN_PASSWORD", None)
    if not admin_email or not admin_password:
        return

    db = SessionLocal()
    try:
        if not db.query(User).filter(User.email == admin_email).first():
            db.add(User(
                email=admin_email,
                hashed_password=hash_password(admin_password),
                full_name="Admin",
                role=UserRole.ADMIN,
                api_token=generate_api_token(),
                credits_total=999_999,
                is_active=True,
            ))
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

_seed_admin()

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
app.include_router(workflows.router,     prefix=f"{settings.API_V1_STR}/workflows", tags=["workflows"])


@app.get("/")
async def root():
    return {"message": "AI Workflow Platform API", "version": settings.VERSION}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
