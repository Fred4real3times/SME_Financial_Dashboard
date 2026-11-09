"""HMAC-signed opaque session tokens with database-backed revocation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from sme_financial_dashboard.db.models import AuthSession, User


class SessionTokenError(ValueError):
    """Raised when a session token is malformed, expired or invalid."""


@dataclass(frozen=True, slots=True)
class SessionClaims:
    session_id: UUID
    user_id: UUID
    expires_at: datetime


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(payload: bytes, secret: str) -> str:
    if len(secret) < 32:
        raise SessionTokenError("SESSION_SECRET must contain at least 32 characters")
    signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return _b64encode(signature)


def issue_session(
    session: Session,
    *,
    user: User,
    secret: str,
    ttl_hours: int = 12,
    now: datetime | None = None,
) -> str:
    if not 1 <= ttl_hours <= 168:
        raise ValueError("Session lifetime must be between 1 and 168 hours")
    current = now or datetime.now(UTC)
    session_id = uuid4()
    expires_at = current + timedelta(hours=ttl_hours)
    payload_data = {
        "v": 1,
        "sid": str(session_id),
        "uid": str(user.id),
        "exp": int(expires_at.timestamp()),
        "nonce": secrets.token_urlsafe(12),
    }
    payload = _b64encode(json.dumps(payload_data, separators=(",", ":"), sort_keys=True).encode())
    signed = payload.encode("ascii")
    token = payload + "." + _sign(signed, secret)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    session.add(
        AuthSession(
            id=session_id,
            user_id=user.id,
            token_hash=token_hash,
            created_at=current,
            expires_at=expires_at,
        )
    )
    session.flush()
    return token


def decode_token(token: str, *, secret: str, allow_expired: bool = False) -> SessionClaims:
    if not isinstance(token, str) or len(token) > 4096 or token.count(".") != 1:
        raise SessionTokenError("Invalid session token")
    payload_part, supplied_signature = token.split(".", maxsplit=1)
    expected_signature = _sign(payload_part.encode("ascii"), secret)
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise SessionTokenError("Invalid session token")
    try:
        data = json.loads(_b64decode(payload_part))
        if data.get("v") != 1:
            raise ValueError("Unsupported token version")
        session_id = UUID(data["sid"])
        user_id = UUID(data["uid"])
        expires_at = datetime.fromtimestamp(int(data["exp"]), tz=UTC)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SessionTokenError("Malformed session token") from exc
    if not allow_expired and expires_at <= datetime.now(UTC):
        raise SessionTokenError("Session has expired")
    return SessionClaims(session_id, user_id, expires_at)


def authenticate_session(session: Session, token: str, *, secret: str) -> User | None:
    try:
        claims = decode_token(token, secret=secret)
    except SessionTokenError:
        return None
    record = session.scalar(select(AuthSession).where(AuthSession.id == claims.session_id))
    if record is None or record.user_id != claims.user_id or record.revoked_at is not None:
        return None
    expiry = record.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    else:
        expiry = expiry.astimezone(UTC)
    if expiry <= datetime.now(UTC):
        return None
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    if not hmac.compare_digest(record.token_hash, token_hash):
        return None
    user = session.scalar(select(User).where(User.id == claims.user_id, User.is_active.is_(True)))
    if user is None:
        return None
    record.last_seen_at = datetime.now(UTC)
    return user


def revoke_session(session: Session, token: str, *, secret: str) -> bool:
    try:
        claims = decode_token(token, secret=secret, allow_expired=True)
    except SessionTokenError:
        return False
    record = session.scalar(select(AuthSession).where(AuthSession.id == claims.session_id))
    if record is None or record.user_id != claims.user_id:
        return False
    if record.revoked_at is None:
        record.revoked_at = datetime.now(UTC)
    return True


def revoke_all_user_sessions(session: Session, *, user_id: UUID) -> int:
    records = session.scalars(
        select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    ).all()
    now = datetime.now(UTC)
    for record in records:
        record.revoked_at = now
    return len(records)
