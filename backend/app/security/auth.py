"""Generic OIDC bearer-token validation and canonical identity resolution.

Supports any standards-compliant OIDC provider (Keycloak, Auth0,
Supabase Auth, etc.) via the OpenID Connect discovery protocol.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal, get_db
from app.events.bus import EventType, event_bus
from app.models.identity import AuthIdentity, Platform, User, UserPlatformMapping
from app.models.user import SlackUser

logger = logging.getLogger(__name__)
settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Verified HiveMind user context for authorization decisions."""

    user_id: uuid.UUID
    workspace_id: uuid.UUID
    email: str | None
    display_name: str
    is_admin: bool
    slack_user_id: str | None = None


class OIDCTokenValidator:
    """Validate access tokens against any OIDC-compliant identity provider.

    Uses the OpenID Connect Discovery protocol to fetch JWKS signing keys
    and validate JWT signatures, audience, issuer, and expiry claims.

    Compatible with: Keycloak, Auth0, Supabase Auth, Authentik, Entra ID.
    """

    def __init__(self) -> None:
        self._metadata: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None
        self._expires_at: datetime | None = None

    async def _load_signing_configuration(
        self,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        now = datetime.now(timezone.utc)
        if (
            self._metadata is not None
            and self._jwks is not None
            and self._expires_at is not None
            and now < self._expires_at
        ):
            return self._metadata, self._jwks

        async with httpx.AsyncClient(timeout=10.0) as client:
            metadata_response = await client.get(settings.oidc_discovery_url_resolved)
            metadata_response.raise_for_status()
            metadata = metadata_response.json()
            jwks_response = await client.get(metadata["jwks_uri"])
            jwks_response.raise_for_status()
            jwks = jwks_response.json()

        self._metadata = metadata
        self._jwks = jwks
        self._expires_at = now + timedelta(hours=24)
        return metadata, jwks

    async def validate(self, token: str) -> dict[str, Any]:
        """Validate signature and required API authorization claims."""
        if not settings.oidc_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API authentication is not configured",
            )

        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid bearer token",
            ) from exc

        try:
            metadata, jwks = await self._load_signing_configuration()

            # Determine accepted algorithms from the provider metadata
            algorithms = metadata.get(
                "id_token_signing_alg_values_supported", ["RS256"]
            )

            key_data = next(
                key
                for key in jwks.get("keys", [])
                if key.get("kid") == header.get("kid")
            )
            alg = key_data.get("alg", "RS256")
            signing_key = jwt.PyJWK.from_dict(key_data, algorithm=alg).key

            claims = jwt.decode(
                token,
                key=signing_key,
                algorithms=algorithms,
                audience=settings.oidc_audience,
                issuer=settings.effective_oidc_issuer,
                options={"require": ["aud", "exp", "iss", "sub"]},
            )
        except StopIteration as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unknown signing key",
            ) from exc
        except HTTPException:
            raise
        except (httpx.HTTPError, KeyError) as exc:
            logger.error("Unable to retrieve OIDC signing configuration: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to validate bearer token",
            ) from exc
        except jwt.PyJWTError as exc:
            logger.warning("Token validation failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer token validation failed",
            ) from exc

        return claims


token_validator = OIDCTokenValidator()


async def _get_slack_mapping(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    result = await session.execute(
        select(UserPlatformMapping.external_user_id).where(
            UserPlatformMapping.user_id == user_id,
            UserPlatformMapping.platform == Platform.SLACK,
            UserPlatformMapping.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def resolve_principal_from_claims(
    session: AsyncSession, claims: dict[str, Any]
) -> tuple[AuthenticatedPrincipal, bool]:
    """Resolve a verified OIDC subject, creating one email match mapping once."""
    issuer = claims["iss"]
    subject = claims["sub"]
    # Keycloak uses 'azp' for client ID; other providers may use 'aud' or 'tid'
    tenant_id = claims.get("azp") or claims.get("tid") or claims.get("aud", "")
    email = claims.get("email") or claims.get("preferred_username") or claims.get("upn")
    normalized_email = email.lower() if isinstance(email, str) else None

    identity_result = await session.execute(
        select(AuthIdentity).where(
            AuthIdentity.issuer == issuer,
            AuthIdentity.subject == subject,
        )
    )
    identity = identity_result.scalar_one_or_none()
    was_created = False

    if identity:
        user = await session.get(User, identity.user_id)
    else:
        if not normalized_email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authenticated account is not mapped to a HiveMind user",
            )
        match_result = await session.execute(
            select(SlackUser).where(func.lower(SlackUser.email) == normalized_email)
        )
        matches = list(match_result.scalars().all())
        if len(matches) != 1:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authenticated account cannot be uniquely mapped",
            )

        slack_user = matches[0]
        user = await session.get(User, slack_user.id)
        if user is None:
            user = User(
                id=slack_user.id,
                workspace_id=slack_user.workspace_id,
                email=slack_user.email,
                display_name=slack_user.display_name,
                is_admin=slack_user.is_admin,
                is_active=slack_user.is_active,
            )
            session.add(user)
            await session.flush()

        identity = AuthIdentity(
            user_id=user.id,
            issuer=issuer,
            subject=subject,
            tenant_id=tenant_id if isinstance(tenant_id, str) else str(tenant_id),
            email=normalized_email,
            last_authenticated_at=datetime.now(timezone.utc),
        )
        session.add(identity)
        await session.flush()
        was_created = True

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="HiveMind user is inactive or unavailable",
        )

    identity.last_authenticated_at = datetime.now(timezone.utc)
    slack_user_id = await _get_slack_mapping(session, user.id)
    principal = AuthenticatedPrincipal(
        user_id=user.id,
        workspace_id=user.workspace_id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        slack_user_id=slack_user_id,
    )
    return principal, was_created


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> AuthenticatedPrincipal:
    """Require an OIDC bearer token and return its canonical HiveMind user."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = await token_validator.validate(credentials.credentials)
    principal, mapping_created = await resolve_principal_from_claims(session, claims)
    if mapping_created:
        await event_bus.publish(
            EventType.IDENTITY_MAPPED,
            {
                "schema_version": 1,
                "user_id": str(principal.user_id),
                "workspace_id": str(principal.workspace_id),
                "identity_provider": "oidc",
            },
        )
    return principal


async def require_admin(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> AuthenticatedPrincipal:
    """Require an authenticated canonical administrator."""
    if not principal.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative permission required",
        )
    return principal


async def resolve_slack_principal(slack_user_id: str) -> AuthenticatedPrincipal | None:
    """Resolve a trusted Slack event actor to the canonical user when mapped."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User, UserPlatformMapping.external_user_id)
            .join(UserPlatformMapping, UserPlatformMapping.user_id == User.id)
            .where(
                UserPlatformMapping.platform == Platform.SLACK,
                UserPlatformMapping.external_user_id == slack_user_id,
                UserPlatformMapping.is_active.is_(True),
                User.is_active.is_(True),
            )
        )
        row = result.first()
        if row is None:
            return None
        user, external_user_id = row
        return AuthenticatedPrincipal(
            user_id=user.id,
            workspace_id=user.workspace_id,
            email=user.email,
            display_name=user.display_name,
            is_admin=user.is_admin,
            slack_user_id=external_user_id,
        )
