"""Authentication and authorization helpers for Clerk-backed admin access."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Annotated, Any

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from app.config import settings

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class CurrentUser:
    user_id: str
    email: str
    claims: dict[str, Any]

    @property
    def audit_actor(self) -> str:
        return self.email or self.user_id


class ClerkJWTVerifier:
    """Verify Clerk JWTs with a small in-process JWKS cache."""

    def __init__(self) -> None:
        self._cached_jwks: dict[str, Any] | None = None
        self._cached_until_monotonic = 0.0
        self._lock = asyncio.Lock()

    async def verify(self, token: str) -> dict[str, Any]:
        if not settings.CLERK_ISSUER or not settings.CLERK_JWKS_URL:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication is not configured on the backend.",
            )

        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise _unauthorized("Malformed JWT header.") from exc

        if header.get("alg") != "RS256":
            raise _unauthorized("Unsupported JWT signing algorithm.")

        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise _unauthorized("JWT is missing a signing key id.")

        signing_key = await self._get_signing_key(kid)
        decode_options = {
            "require": ["exp", "iat", "nbf", "iss", "sub"],
            "verify_aud": bool(settings.CLERK_AUDIENCE),
        }

        try:
            claims = jwt.decode(
                token,
                key=signing_key,
                algorithms=["RS256"],
                issuer=settings.CLERK_ISSUER,
                audience=settings.CLERK_AUDIENCE or None,
                leeway=settings.CLERK_CLOCK_SKEW_SECONDS,
                options=decode_options,
            )
        except InvalidTokenError as exc:
            raise _unauthorized("Invalid or expired Clerk token.") from exc

        if not isinstance(claims, dict):
            raise _unauthorized("JWT payload is invalid.")

        return claims

    async def _get_signing_key(self, kid: str) -> Any:
        jwks = await self._get_jwks()
        key = _find_jwk(jwks, kid)
        if key is None:
            jwks = await self._get_jwks(force_refresh=True)
            key = _find_jwk(jwks, kid)

        if key is None:
            raise _unauthorized("No matching signing key found for JWT.")

        return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))

    async def _get_jwks(self, *, force_refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if (
            not force_refresh
            and self._cached_jwks is not None
            and now < self._cached_until_monotonic
        ):
            return self._cached_jwks

        async with self._lock:
            now = time.monotonic()
            if (
                not force_refresh
                and self._cached_jwks is not None
                and now < self._cached_until_monotonic
            ):
                return self._cached_jwks

            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(settings.CLERK_JWKS_URL)
                    response.raise_for_status()
                    payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Unable to fetch Clerk JWKS for token verification.",
                ) from exc

            if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Clerk JWKS response is malformed.",
                )

            self._cached_jwks = payload
            self._cached_until_monotonic = (
                now + max(settings.CLERK_JWKS_CACHE_TTL_SECONDS, 1)
            )
            return payload


verifier = ClerkJWTVerifier()


async def get_authenticated_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> CurrentUser:
    if (
        credentials is None
        and settings.ENVIRONMENT != "production"
        and settings.ALLOW_INSECURE_DEV_AUTH_BYPASS
    ):
        return CurrentUser(
            user_id="dev-auth-bypass",
            email=settings.DEV_AUTH_BYPASS_EMAIL,
            claims={"bypass": True, "email": settings.DEV_AUTH_BYPASS_EMAIL},
        )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Missing bearer token.")

    claims = await verifier.verify(credentials.credentials)
    email = _extract_email(claims)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated Clerk token does not include an email claim.",
        )

    user_id = claims.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise _unauthorized("JWT payload is missing a valid subject.")

    return CurrentUser(
        user_id=user_id,
        email=email,
        claims=claims,
    )


async def require_admin_user(
    current_user: Annotated[CurrentUser, Depends(get_authenticated_user)],
) -> CurrentUser:
    if settings.is_email_allowed(current_user.email):
        return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Authenticated user is not authorized for this admin API.",
    )


def _extract_email(claims: dict[str, Any]) -> str | None:
    for key in ("email", "primaryEmail", "email_address"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def _find_jwk(jwks: dict[str, Any], kid: str) -> dict[str, Any] | None:
    keys = jwks.get("keys", [])
    if not isinstance(keys, list):
        return None
    for key in keys:
        if isinstance(key, dict) and key.get("kid") == kid:
            return key
    return None


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)
