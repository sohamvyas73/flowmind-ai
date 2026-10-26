import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.auth import (
    hash_password, verify_password, create_access_token,
    generate_api_token, set_api_token, get_current_user, get_current_user_allow_inactive,
)
from app.core.ratelimit import limiter, limit_auth, client_ip
from app.core.config import settings
from app.models.user import User
from app.schemas.user import UserCreate, UserLogin, TokenResponse, UserResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(data: UserCreate, request: Request, db: Session = Depends(get_db)):
    limit_auth(request)
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
    )
    api_token = generate_api_token()
    set_api_token(user, api_token)
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id)})
    logger.info("New user signed up: %s", user.email)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user), api_token=api_token)


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, request: Request, db: Session = Depends(get_db)):
    limit_auth(request)
    # Per-account throttle too, so a distributed attack on one email is still slowed
    limiter.check(f"login:{data.email}", settings.AUTH_RATE_LIMIT_PER_MIN)
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token({"sub": str(user.id)})
    logger.info("User logged in: %s", user.email)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user_allow_inactive)):
    return UserResponse.model_validate(current_user)


@router.post("/refresh-api-token", response_model=TokenResponse)
async def refresh_api_token(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rotate the static API token. The plaintext is returned once and never stored."""
    api_token = generate_api_token()
    set_api_token(current_user, api_token)
    db.commit()
    db.refresh(current_user)
    logger.info("API token refreshed for user: %s", current_user.email)
    return TokenResponse(
        access_token=create_access_token({"sub": str(current_user.id)}),
        user=UserResponse.model_validate(current_user),
        api_token=api_token,
    )
