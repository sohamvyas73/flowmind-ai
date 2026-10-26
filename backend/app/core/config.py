from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "AI Workflow Platform"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    DATABASE_URL: str = "postgresql://user:password@localhost/ai_workflow"
    REDIS_URL: str = "redis://localhost:6379"
    
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o"
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-1.5-pro"
    
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 43200  # 30 days

    # Code Runner executes user Python in-process; enable only in a trusted/sandboxed deployment.
    ENABLE_CODE_NODE: bool = False
    # Key used to encrypt provider keys / node secrets at rest (falls back to SECRET_KEY)
    ENCRYPTION_KEY: Optional[str] = None
    # SSRF guard for HTTP/KYC nodes; only enable for local development against private services
    ALLOW_PRIVATE_URLS: bool = False
    # In-memory rate limits (per process, per minute)
    AUTH_RATE_LIMIT_PER_MIN: int = 10
    TRIGGER_RATE_LIMIT_PER_MIN: int = 60
    # 0 = static API tokens never expire; otherwise tokens older than this must be rotated
    API_TOKEN_TTL_DAYS: int = 0
    # Execution traces/inputs/outputs older than this are purged (0 = keep forever)
    EXECUTION_RETENTION_DAYS: int = 30

    # ── Background jobs (PostgreSQL-backed queue) ──────────────────────────────
    WORKER_ENABLED: bool = True           # run an embedded worker inside the API process
    WORKER_CONCURRENCY: int = 2
    JOB_POLL_SECONDS: float = 1.0
    JOB_LEASE_SECONDS: int = 60           # a worker must heartbeat within this window
    JOB_MAX_ATTEMPTS: int = 3
    JOB_RETRY_BASE_SECONDS: int = 10      # backoff: base * 2^(attempt-1)
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_TICK_SECONDS: float = 15.0
    MAX_SCHEDULES_PER_USER: int = 20
    MIN_SCHEDULE_INTERVAL_SECONDS: int = 60
    MAX_CONNECTIONS_PER_USER: int = 50

    ADMIN_EMAIL: Optional[str] = None
    ADMIN_PASSWORD: Optional[str] = None

    CORS_ORIGINS: list = ["http://localhost:3000", "http://localhost:5173"]
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
