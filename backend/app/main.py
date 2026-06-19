import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.core.config import settings
from app.core.database import Base, engine, SessionLocal
from app.api import workflows
from app.api import auth as auth_router
from app.api import admin as admin_router

# Register all models with Base before create_all
from app.models import workflow as _wf_models  # noqa: F401
from app.models import user as _user_models    # noqa: F401

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Create all tables
Base.metadata.create_all(bind=engine)

# Idempotent schema migration: add user_id to existing workflows table
try:
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE workflows ADD COLUMN IF NOT EXISTS "
            "user_id UUID REFERENCES users(id) ON DELETE SET NULL;"
        ))
        conn.commit()
except Exception as e:
    logger.warning("Schema migration skipped (table may not exist yet): %s", e)

# Seed admin user from environment variables
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
            ))
            db.commit()
            logger.info("Admin user created: %s", admin_email)
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

app.include_router(auth_router.router,  prefix=f"{settings.API_V1_STR}/auth",     tags=["auth"])
app.include_router(admin_router.router, prefix=f"{settings.API_V1_STR}/admin",    tags=["admin"])
app.include_router(workflows.router,    prefix=f"{settings.API_V1_STR}/workflows", tags=["workflows"])


@app.get("/")
async def root():
    return {"message": "AI Workflow Platform API", "version": settings.VERSION}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
