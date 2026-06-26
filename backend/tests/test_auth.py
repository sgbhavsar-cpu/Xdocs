"""Auth tests: JWT/JWKS validation + permission mapping + /me flow.

Covers test cases A-02..A-05 and the permission model.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.auth.deps import get_verifier
from app.auth.jwt import TokenVerifier
from app.auth.permissions import Permission, principal_from_claims
from app.core.errors import UnauthorizedError
from app.main import app

# ---- TokenVerifier (signature/claim validation) ----


def test_valid_token_verifies(verifier: TokenVerifier, make_token: Callable[..., str]) -> None:
    claims = verifier.verify(make_token(roles=["reader"]))
    assert claims["sub"] == "user-1"


def test_expired_token_rejected(verifier: TokenVerifier, make_token: Callable[..., str]) -> None:
    with pytest.raises(UnauthorizedError, match="expired"):
        verifier.verify(make_token(expires_in=-10))


def test_wrong_audience_rejected(verifier: TokenVerifier, make_token: Callable[..., str]) -> None:
    with pytest.raises(UnauthorizedError, match="audience"):
        verifier.verify(make_token(audience="someone-else"))


def test_wrong_issuer_rejected(verifier: TokenVerifier, make_token: Callable[..., str]) -> None:
    with pytest.raises(UnauthorizedError, match="issuer"):
        verifier.verify(make_token(issuer="https://evil.example"))


def test_bad_signature_rejected(verifier: TokenVerifier, make_token: Callable[..., str]) -> None:
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(UnauthorizedError):
        verifier.verify(make_token(roles=["reader"], key=other_key))


# ---- Permission mapping ----


def test_role_and_scope_mapping() -> None:
    p = principal_from_claims(
        {
            "sub": "u",
            "email": "u@x.io",
            "roles": ["reader"],
            "scopes": ["space:platform:write", "space:sql-server:read"],
        }
    )
    assert p.global_permission == Permission.READ
    assert p.can("platform", Permission.WRITE)  # explicit scope grants write
    assert p.can("sql-server", Permission.READ)
    assert not p.can("sql-server", Permission.WRITE)
    # A space with no explicit scope falls back to the global role permission.
    assert p.can("unknown-space", Permission.READ)
    assert not p.can("unknown-space", Permission.WRITE)


# ---- /me endpoint (story A6) ----


def test_me_endpoint(verifier: TokenVerifier, make_token: Callable[..., str]) -> None:
    app.dependency_overrides[get_verifier] = lambda: verifier
    try:
        client = TestClient(app)
        token = make_token(roles=["editor"], scopes=["space:sql-server:admin"])
        resp = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["sub"] == "user-1"
        assert body["global_permission"] == "write"
        assert body["space_permissions"] == {"sql-server": "admin"}
    finally:
        app.dependency_overrides.clear()


def test_me_requires_token() -> None:
    client = TestClient(app)
    resp = client.get("/api/v1/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
