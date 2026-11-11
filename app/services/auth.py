from datetime import UTC
from datetime import datetime
from datetime import timedelta
from uuid import UUID
from uuid import uuid4

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings

password_hash = PasswordHash.recommended()
_DUMMY_PASSWORD_HASH = password_hash.hash("dummy-password-not-used-for-login")
JWT_ISSUER = "nexora"
JWT_AUDIENCE = "nexora-api"
JWT_ALGORITHM = "HS256"


def _secret(settings: Settings) -> str:
    if not settings.jwt_secret_key:
        raise RuntimeError("NEXORA_JWT_SECRET_KEY is not configured")
    return settings.jwt_secret_key


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return password_hash.verify(password, stored_hash)
    except (ValueError, TypeError):
        return False


def verify_unknown_user_password(password: str) -> None:
    password_hash.verify(password, _DUMMY_PASSWORD_HASH)


def create_access_token(user_id: UUID, settings: Settings) -> tuple[str, int]:
    expires_in = settings.access_token_expire_minutes * 60
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
            "type": "access",
            "jti": str(uuid4()),
        },
        _secret(settings),
        algorithm=JWT_ALGORITHM,
    )
    return token, expires_in


def decode_access_token(token: str, settings: Settings) -> UUID:
    try:
        claims = jwt.decode(
            token,
            _secret(settings),
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
            options={"require": ["sub", "iat", "exp", "iss", "aud", "type", "jti"]},
        )
        if claims.get("type") != "access":
            raise ValueError("Unsupported token type")
        return UUID(claims["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError, RuntimeError) as error:
        raise ValueError("Invalid access token") from error
