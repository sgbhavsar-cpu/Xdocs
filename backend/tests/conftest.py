"""Shared test fixtures.

Generates an in-process RSA keypair and exposes it as a static JWK set so JWT
validation runs fully offline (no JWKS network fetch), exercising the real
signature/claim verification path.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.jwt import TokenVerifier

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
