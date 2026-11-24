"""API key authentication dependency.

Validates an `X-API-Key` header against the api_keys table via the
APIKeyRepository. Designed to be the single shared dependency for
all protected routes so adding rate limiting, scope checks, or
audit logging in a follow-up touches one place.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import redis
from fastapi import Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth.rate_limit import DEFAULT_LIMIT, get_redis, hit
from app.db import SessionLocal
from app.models.api_key import ApiKey
from app.repositories.api_keys import APIKeyRepository


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def api_key_auth(
    response: Response,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
    r: redis.Redis = Depends(get_redis),
) -> ApiKey:
    if x_api_key is None or not x_api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing api key",
        )
    repo = APIKeyRepository(db)
    key = repo.get_by_key(x_api_key)
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid api key",
        )
    result = hit(r, int(key.id), int(key.requests_per_minute or DEFAULT_LIMIT))
    if not result.allowed:
        retry_after = max(result.reset - int(time.time()), 1)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
            headers={**result.headers(), "Retry-After": str(retry_after)},
        )
    response.headers.update(result.headers())
    return key
