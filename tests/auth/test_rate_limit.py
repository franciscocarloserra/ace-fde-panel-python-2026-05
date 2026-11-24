"""Acceptance tests for per-API-key rate limiting (100 req/min)."""

from __future__ import annotations

from collections.abc import Iterator

import fakeredis
import pytest
import redis
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.api_key import api_key_auth, get_db
from app.auth.rate_limit import get_redis, hit
from app.db import Base
from app.models.api_key import ApiKey
from app.models.run import Run as _Run
from app.models.workflow import Workflow as _Workflow

_REGISTERED = (_Run, _Workflow)


@pytest.fixture
def fake_redis() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis()


@pytest.fixture
def client(fake_redis: fakeredis.FakeRedis) -> Iterator[TestClient]:
    assert _REGISTERED
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    seed = factory()
    seed.add_all([
        ApiKey(key="ak_a", user_id=1, name="a"),
        ApiKey(key="ak_b", user_id=2, name="b"),
        ApiKey(key="ak_small", user_id=3, name="small", requests_per_minute=3),
    ])
    seed.commit()
    seed.close()

    app = FastAPI()

    @app.get("/protected")
    def protected(caller: ApiKey = Depends(api_key_auth)) -> dict[str, str]:
        return {"name": caller.name}

    def _db() -> Iterator[Session]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = lambda: fake_redis
    yield TestClient(app)
    engine.dispose()


def _get(client: TestClient, key: str) -> Response:
    return client.get("/protected", headers={"X-API-Key": key})


def test_headers_on_success(client: TestClient) -> None:
    resp = client.get("/protected", headers={"X-API-Key": "ak_a"})
    assert resp.status_code == 200
    assert resp.headers["X-RateLimit-Limit"] == "100"
    assert resp.headers["X-RateLimit-Remaining"] == "99"
    assert int(resp.headers["X-RateLimit-Reset"]) % 60 == 0


def test_101st_request_gets_429(client: TestClient) -> None:
    for _ in range(100):
        assert _get(client, "ak_a").status_code == 200
    resp = client.get("/protected", headers={"X-API-Key": "ak_a"})
    assert resp.status_code == 429
    assert resp.headers["X-RateLimit-Remaining"] == "0"
    assert "Retry-After" in resp.headers


def test_limit_is_per_key(client: TestClient) -> None:
    for _ in range(101):
        client.get("/protected", headers={"X-API-Key": "ak_a"})
    assert client.get("/protected", headers={"X-API-Key": "ak_b"}).status_code == 200


def test_per_key_override(client: TestClient) -> None:
    codes = [_get(client, "ak_small").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_window_resets_each_minute(fake_redis: fakeredis.FakeRedis) -> None:
    t0 = 1_800_000_000.0  # aligned to a minute boundary
    assert not [hit(fake_redis, 1, 2, t0) for _ in range(3)][-1].allowed
    assert hit(fake_redis, 1, 2, t0 + 60).allowed


def test_redis_down_fails_open() -> None:
    dead = redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.1)
    assert hit(dead, 1, 100).allowed
