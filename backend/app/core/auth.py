import secrets
from uuid import UUID
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.core.secrets import hash_api_token, token_prefix

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def generate_api_token() -> str:
    return secrets.token_hex(32)


def set_api_token(user, token: str) -> None:
    """Store only the hash + display prefix; the caller must show `token` to the user once."""
    user.api_token_hash = hash_api_token(token)
    user.api_token_prefix = token_prefix(token)
    user.api_token_created_at = datetime.utcnow()
    user.api_token = None


async def get_current_user_allow_inactive(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    from app.models.user import User

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Try JWT first
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id:
            user = db.query(User).filter(User.id == UUID(str(user_id))).first()
            if user:
                return user
    except (JWTError, ValueError):
        pass

    # Fall back to static API token (stored hashed)
    user = db.query(User).filter(User.api_token_hash == hash_api_token(token)).first()
    if user:
        ttl = settings.API_TOKEN_TTL_DAYS
        if ttl and user.api_token_created_at and datetime.utcnow() - user.api_token_created_at > timedelta(days=ttl):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API token expired. Rotate it in the app.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(user=Depends(get_current_user_allow_inactive)):
    """Authenticated AND approved user. Inactive accounts get 403 (not 401) so clients can show a pending-approval state."""
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account not yet activated. Please contact your admin.")
    return user


async def get_admin_user(current_user=Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user
