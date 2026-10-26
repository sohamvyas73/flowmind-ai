"""Startup data migrations (secrets hardening) and execution-data retention."""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.secrets import (
    dump_secrets, encrypt, extract_graph_secrets, hash_api_token, load_secrets, token_prefix,
)

logger = logging.getLogger(__name__)

_KEY_COLUMNS = [
    ("users", "openai_api_key"), ("users", "anthropic_api_key"), ("users", "gemini_api_key"),
    ("platform_settings", "openai_api_key"), ("platform_settings", "anthropic_api_key"),
    ("platform_settings", "gemini_api_key"),
]


def migrate_secrets() -> None:
    """One-time, idempotent: hash legacy API tokens, encrypt legacy provider keys, vault node secrets."""
    try:
        with engine.begin() as conn:
            # 1. Static API tokens: plaintext -> hash + prefix
            rows = conn.execute(text(
                "SELECT id, api_token FROM users WHERE api_token IS NOT NULL AND api_token_hash IS NULL"
            )).fetchall()
            for uid, token in rows:
                conn.execute(
                    text("UPDATE users SET api_token_hash=:h, api_token_prefix=:p, api_token_created_at=:t, api_token=NULL WHERE id=:id"),
                    {"h": hash_api_token(token), "p": token_prefix(token), "t": datetime.utcnow(), "id": uid},
                )
            if rows:
                logger.info("Hashed %d legacy API token(s); users must rotate to view their token again", len(rows))

            # 2. Provider keys: plaintext -> encrypted
            for table, col in _KEY_COLUMNS:
                pk = "id"
                legacy = conn.execute(text(
                    f"SELECT {pk}, {col} FROM {table} WHERE {col} IS NOT NULL AND {col} <> '' AND {col} NOT LIKE 'enc:v1:%'"
                )).fetchall()
                for rid, val in legacy:
                    conn.execute(text(f"UPDATE {table} SET {col}=:v WHERE {pk}=:id"), {"v": encrypt(val), "id": rid})
                if legacy:
                    logger.info("Encrypted %d legacy value(s) in %s.%s", len(legacy), table, col)
    except Exception as e:
        logger.warning("Secret migration (tokens/keys) skipped: %s", e)

    # 3. Workflow node secrets: graph_data plaintext -> encrypted vault column
    from app.models.workflow import Workflow
    db = SessionLocal()
    try:
        moved = 0
        for wf in db.query(Workflow).all():
            clean, secrets = extract_graph_secrets(wf.graph_data or {}, load_secrets(wf.secrets))
            if secrets and clean != wf.graph_data:
                wf.graph_data = clean
                wf.secrets = dump_secrets(secrets)
                moved += 1
        if moved:
            db.commit()
            logger.info("Moved node secrets out of graph_data for %d workflow(s)", moved)
    except Exception as e:
        db.rollback()
        logger.warning("Secret migration (workflows) skipped: %s", e)
    finally:
        db.close()


def purge_old_executions() -> int:
    days = settings.EXECUTION_RETENTION_DAYS
    if days <= 0:
        return 0
    from app.models.workflow import WorkflowExecution
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        n = db.query(WorkflowExecution).filter(WorkflowExecution.started_at < cutoff).delete()
        db.commit()
        if n:
            logger.info("Retention: purged %d execution(s) older than %d days", n, days)
        return n
    except Exception as e:
        db.rollback()
        logger.warning("Retention purge failed: %s", e)
        return 0
    finally:
        db.close()


async def retention_loop(interval_s: int = 6 * 3600) -> None:
    from app.services.dataset_service import purge_expired_datasets
    while True:
        await asyncio.to_thread(purge_old_executions)
        await asyncio.to_thread(purge_expired_datasets)
        await asyncio.sleep(interval_s)
