"""Shared test fixtures.

Generates an in-process RSA keypair and exposes it as a static JWK set so JWT
validation runs fully offline (no JWKS network fetch), exercising the real
signature/claim verification path.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (register ORM models on Base.metadata)
from app.auth.jwt import TokenVerifier
from app.core.db import Base, get_session
from app.llm.guard import LlmGuard, get_llm_guard
from app.main import app
from app.scripts.seed import seed

ISSUER = "https://mock-idp.local"
AUDIENCE = "xdocs"
KID = "test-key-1"


@pytest.fixture(scope="session")
def rsa_private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def static_jwks(rsa_private_key: rsa.RSAPrivateKey) -> dict[str, Any]:
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(rsa_private_key.public_key(), as_dict=True)
    jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


@pytest.fixture
def verifier(static_jwks: dict[str, Any]) -> TokenVerifier:
    return TokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        algorithms=["RS256"],
        static_jwks=static_jwks,
    )


@pytest.fixture
def make_token(rsa_private_key: rsa.RSAPrivateKey) -> Callable[..., str]:
    def _make(
        *,
        sub: str = "user-1",
        email: str = "u@example.com",
        roles: list[str] | None = None,
        scopes: list[str] | None = None,
        audience: str = AUDIENCE,
        issuer: str = ISSUER,
        expires_in: int = 3600,
        kid: str = KID,
        key: rsa.RSAPrivateKey | None = None,
    ) -> str:
        now = int(time.time())
        claims = {
            "sub": sub,
            "email": email,
            "roles": roles or [],
            "scopes": scopes or [],
            "aud": audience,
            "iss": issuer,
            "iat": now,
            "exp": now + expires_in,
        }
        return jwt.encode(claims, key or rsa_private_key, algorithm="RS256", headers={"kid": kid})

    return _make


# ---- Content API fixtures (SQLite-backed, seeded) ----


@pytest_asyncio.fixture
async def seeded_client() -> AsyncIterator[tuple[AsyncClient, AsyncSession]]:
    """An ASGI client + session backed by an in-memory SQLite DB seeded with demo data.

    Content endpoints read through the overridden `get_session`, so both the seed
    and the requests share one session in a single event loop.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as session:
        await seed(session)

        async def _override_session() -> AsyncIterator[AsyncSession]:
            yield session

        app.dependency_overrides[get_session] = _override_session
        # Fresh, permissive guard per test so rate/budget state doesn't leak.
        app.dependency_overrides[get_llm_guard] = lambda: LlmGuard(
            rate_per_min=1000, token_budget=10**9
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, session

    app.dependency_overrides.clear()
    await engine.dispose()
