"""JWT validation against a JWKS endpoint (host-issued tokens, design §16.1).

The verifier is constructed from settings in production (fetching the host IdP's
JWKS), but accepts a static JWK set for offline/unit testing so the real
signature-validation path is exercised without a network call.
"""

from __future__ import annotations

from typing import Any

import jwt
from jwt import PyJWKClient, PyJWKSet

from app.core.errors import UnauthorizedError


class TokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        algorithms: list[str],
        jwks_url: str | None = None,
        static_jwks: dict[str, Any] | None = None,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self.algorithms = algorithms
        self._jwks_url = jwks_url
        self._static = PyJWKSet.from_dict(static_jwks) if static_jwks else None
        self._client: PyJWKClient | None = None

    def _signing_key(self, token: str) -> Any:
        if self._static is not None:
            kid = jwt.get_unverified_header(token).get("kid")
            for key in self._static.keys:
                if key.key_id == kid:
                    return key.key
            # Single-key dev sets may omit kid; fall back to the first key.
            if self._static.keys and kid is None:
                return self._static.keys[0].key
            raise UnauthorizedError("No matching signing key (kid).", details={"kid": kid})
        if self._client is None:
            if not self._jwks_url:
                raise UnauthorizedError("No JWKS source configured.")
            self._client = PyJWKClient(self._jwks_url)
        return self._client.get_signing_key_from_jwt(token).key

    def verify(self, token: str) -> dict[str, Any]:
        try:
            key = self._signing_key(token)
            return jwt.decode(
                token,
                key,
                algorithms=self.algorithms,
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise UnauthorizedError("Token has expired.") from exc
        except jwt.InvalidAudienceError as exc:
            raise UnauthorizedError("Invalid audience.") from exc
        except jwt.InvalidIssuerError as exc:
            raise UnauthorizedError("Invalid issuer.") from exc
        except jwt.InvalidSignatureError as exc:
            raise UnauthorizedError("Invalid signature.") from exc
        except jwt.PyJWTError as exc:
            raise UnauthorizedError("Invalid token.") from exc
