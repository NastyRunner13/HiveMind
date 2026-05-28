"""OIDC authentication and canonical identity resolution tests."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app.security.auth import (
    OIDCTokenValidator,
    get_current_principal,
    resolve_principal_from_claims,
)


@pytest.fixture
def oidc_settings():
    return SimpleNamespace(
        oidc_configured=True,
        oidc_audience="hivemind-api",
        effective_oidc_issuer="http://localhost:8080/realms/hivemind",
        oidc_discovery_url_resolved="http://localhost:8080/realms/hivemind/.well-known/openid-configuration",
    )


@pytest.fixture
def signing_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(
        jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key())
    )
    public_jwk["kid"] = "key-id"
    public_jwk["alg"] = "RS256"
    return private_key, public_jwk


def _claims(**updates):
    claims = {
        "iss": "http://localhost:8080/realms/hivemind",
        "sub": "subject-id",
        "azp": "hivemind-api",
        "aud": "hivemind-api",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        "email": "user@example.com",
    }
    claims.update(updates)
    return claims


async def _validate_token(claims, key, jwk, settings):
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "key-id"})
    validator = OIDCTokenValidator()
    validator._load_signing_configuration = AsyncMock(
        return_value=(
            {
                "issuer": settings.effective_oidc_issuer,
                "id_token_signing_alg_values_supported": ["RS256"],
            },
            {"keys": [jwk]},
        )
    )
    with patch("app.security.auth.settings", settings):
        return await validator.validate(token)


@pytest.mark.asyncio
async def test_valid_oidc_access_token_is_accepted(oidc_settings, signing_material):
    private_key, public_jwk = signing_material
    claims = await _validate_token(_claims(), private_key, public_jwk, oidc_settings)
    assert claims["sub"] == "subject-id"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed_claim",
    [
        {"aud": "wrong-api"},
        {"iss": "https://evil-server.com/realms/fake"},
        {"exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
    ],
)
async def test_invalid_oidc_token_claims_are_rejected(
    changed_claim, oidc_settings, signing_material
):
    private_key, public_jwk = signing_material
    with pytest.raises(HTTPException) as error:
        await _validate_token(
            _claims(**changed_claim), private_key, public_jwk, oidc_settings
        )
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_signature_is_rejected(oidc_settings, signing_material):
    _, public_jwk = signing_material
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(HTTPException) as error:
        await _validate_token(_claims(), attacker_key, public_jwk, oidc_settings)
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_missing_bearer_token_is_rejected():
    with pytest.raises(HTTPException) as error:
        await get_current_principal(credentials=None, session=AsyncMock())
    assert error.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("matches", [[], [MagicMock(), MagicMock()]])
async def test_unmapped_or_ambiguous_email_mapping_is_denied(matches):
    session = AsyncMock()
    identity_result = MagicMock()
    identity_result.scalar_one_or_none.return_value = None
    matches_result = MagicMock()
    matches_result.scalars.return_value.all.return_value = matches
    session.execute = AsyncMock(side_effect=[identity_result, matches_result])
    with pytest.raises(HTTPException) as error:
        await resolve_principal_from_claims(session, _claims())
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_existing_identity_resolves_canonical_principal():
    user_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    identity = MagicMock(user_id=user_id)
    user = MagicMock(
        id=user_id,
        workspace_id=workspace_id,
        email="user@example.com",
        display_name="User",
        is_admin=False,
        is_active=True,
    )
    identity_result = MagicMock()
    identity_result.scalar_one_or_none.return_value = identity
    mapping_result = MagicMock()
    mapping_result.scalar_one_or_none.return_value = "U123"
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[identity_result, mapping_result])
    session.get = AsyncMock(return_value=user)

    principal, was_created = await resolve_principal_from_claims(session, _claims())

    assert was_created is False
    assert principal.user_id == user_id
    assert principal.workspace_id == workspace_id
    assert principal.slack_user_id == "U123"


@pytest.mark.asyncio
async def test_oidc_not_configured_returns_503():
    """When OIDC settings are empty, validate should return 503."""
    unconfigured = SimpleNamespace(oidc_configured=False)
    validator = OIDCTokenValidator()
    with (
        patch("app.security.auth.settings", unconfigured),
        pytest.raises(HTTPException) as error,
    ):
        await validator.validate("some.fake.token")
    assert error.value.status_code == 503
