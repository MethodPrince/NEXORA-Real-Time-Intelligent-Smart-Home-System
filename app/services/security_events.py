import logging
from collections.abc import Mapping
from uuid import UUID

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import SecurityEvent

logger = logging.getLogger(__name__)


def _source_ip(request: Request | None, source_ip: str | None) -> str | None:
    if source_ip is not None:
        return source_ip[:45]
    if request is None or request.client is None:
        return None
    return request.client.host[:45]


def add_security_event(
    session: Session,
    *,
    event_type: str,
    severity: str,
    source: str,
    outcome: str,
    user_id: UUID | None = None,
    home_id: UUID | None = None,
    request: Request | None = None,
    source_ip: str | None = None,
    metadata: Mapping[str, object] | None = None,
    response: str | None = None,
) -> None:
    session.add(
        SecurityEvent(
            user_id=user_id,
            home_id=home_id,
            event_type=event_type,
            severity=severity,
            source=source[:200],
            source_ip=_source_ip(request, source_ip),
            outcome=outcome[:40],
            metadata_json=dict(metadata or {}),
            response=response,
        )
    )


def record_security_event(
    session: Session,
    *,
    event_type: str,
    severity: str,
    source: str,
    outcome: str,
    user_id: UUID | None = None,
    home_id: UUID | None = None,
    request: Request | None = None,
    source_ip: str | None = None,
    metadata: Mapping[str, object] | None = None,
    response: str | None = None,
) -> None:
    add_security_event(
        session,
        event_type=event_type,
        severity=severity,
        source=source,
        outcome=outcome,
        user_id=user_id,
        home_id=home_id,
        request=request,
        source_ip=source_ip,
        metadata=metadata,
        response=response,
    )
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        logger.exception("Could not persist security event %s", event_type)
        raise
