import logging
from datetime import UTC
from datetime import datetime
from typing import Annotated
from uuid import UUID
from typing import NoReturn

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.dependencies import get_db_session
from app.db.dependencies import require_non_guest
from app.db.dependencies import user_can_access_device
from app.db.dependencies import HomeAccess
from app.db.models import AutomationRule
from app.db.models import Device
from app.services.security_events import record_security_event
from app.api.schemas.automations import AutomationAction
from app.api.schemas.automations import AutomationCreate
from app.api.schemas.automations import AutomationRead
from app.api.schemas.automations import AutomationUpdate
from app.api.schemas.automations import ScheduleTrigger
from app.services.automation_scheduler import next_run_time
from app.services.automation_scheduler import validate_device_action

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/automations", tags=["automations"])


def _raise_database_error(operation: str, error: SQLAlchemyError) -> NoReturn:
    logger.exception("Automation %s failed", operation)
    raise HTTPException(
        status_code=503,
        detail="Database operation unavailable",
    ) from error


def _response(rule: AutomationRule) -> AutomationRead:
    return AutomationRead(
        id=rule.id,
        name=rule.name,
        description=rule.description,
        trigger=ScheduleTrigger.model_validate(rule.trigger_conditions),
        action=AutomationAction.model_validate(rule.actions[0]),
        enabled=rule.enabled,
        next_run_at=rule.next_run_at,
        last_run_at=rule.last_run_at,
        last_error=rule.last_error,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _validate_device_action(
    session: Session,
    action: AutomationAction,
    access: HomeAccess,
    request: Request,
) -> None:
    device = session.scalar(
        select(Device).where(
            Device.id == action.device_id,
            Device.home_id == access.home.id,
        )
    )
    if device is None or not user_can_access_device(
        session,
        access.user,
        action.device_id,
        control=True,
        home_id=access.home.id,
    ):
        record_security_event(
            session,
            event_type="automation_permission_denied",
            severity="warning",
            source="/automations",
            outcome="denied",
            user_id=access.user.id,
            home_id=access.home.id,
            request=request,
            metadata={"device_id": str(action.device_id), "reason": "not_controlled"},
        )
        raise HTTPException(status_code=404, detail="Automation device not found")
    try:
        validate_device_action(device, action.command)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("", response_model=list[AutomationRead])
def list_automations(
    session: Annotated[Session, Depends(get_db_session)],
    access: Annotated[HomeAccess, Depends(require_non_guest)],
) -> list[AutomationRead]:
    statement = select(AutomationRule).where(
        AutomationRule.home_id == access.home.id
    )
    if access.role.value != "ADMIN":
        statement = statement.where(AutomationRule.owner_user_id == access.user.id)
    try:
        rules = session.scalars(
            statement.order_by(AutomationRule.created_at.desc())
        )
        return [_response(rule) for rule in rules]
    except SQLAlchemyError as error:
        _raise_database_error("listing", error)


@router.post("", response_model=AutomationRead, status_code=201)
def create_automation(
    request: Request,
    rule_data: AutomationCreate,
    session: Annotated[Session, Depends(get_db_session)],
    access: Annotated[HomeAccess, Depends(require_non_guest)],
) -> AutomationRead:
    try:
        _validate_device_action(session, rule_data.action, access, request)
        trigger = rule_data.trigger.model_dump(mode="json")
        rule = AutomationRule(
            home_id=access.home.id,
            name=rule_data.name,
            description=rule_data.description,
            trigger_conditions=trigger,
            actions=[rule_data.action.model_dump(mode="json")],
            owner_user_id=access.user.id,
            enabled=rule_data.enabled,
            next_run_at=(
                next_run_time(trigger, datetime.now(UTC)) if rule_data.enabled else None
            ),
        )
        session.add(rule)
        session.commit()
        session.refresh(rule)
    except HTTPException:
        session.rollback()
        raise
    except SQLAlchemyError as error:
        session.rollback()
        _raise_database_error("creation", error)
    return _response(rule)


@router.patch("/{automation_id}", response_model=AutomationRead)
def update_automation(
    automation_id: UUID,
    request: Request,
    rule_data: AutomationUpdate,
    session: Annotated[Session, Depends(get_db_session)],
    access: Annotated[HomeAccess, Depends(require_non_guest)],
) -> AutomationRead:
    values = rule_data.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=422, detail="At least one field must be provided")
    try:
        statement = select(AutomationRule).where(
            AutomationRule.id == automation_id,
            AutomationRule.home_id == access.home.id,
        )
        if access.role.value != "ADMIN":
            statement = statement.where(AutomationRule.owner_user_id == access.user.id)
        rule = session.scalar(statement)
        if rule is None:
            record_security_event(
                session,
                event_type="automation_permission_denied",
                severity="warning",
                source="/automations/{automation_id}",
                outcome="denied",
                user_id=access.user.id,
                home_id=access.home.id,
                request=request,
                metadata={"automation_id": str(automation_id), "method": "PATCH"},
            )
            raise HTTPException(status_code=404, detail="Automation not found")
        if rule_data.action is not None:
            _validate_device_action(session, rule_data.action, access, request)
            rule.actions = [rule_data.action.model_dump(mode="json")]
        if rule_data.trigger is not None:
            rule.trigger_conditions = rule_data.trigger.model_dump(mode="json")
        if "name" in values:
            if rule_data.name is None:
                raise HTTPException(status_code=422, detail="name cannot be null")
            rule.name = rule_data.name
        if "description" in values:
            rule.description = rule_data.description
        if "enabled" in values:
            if rule_data.enabled is None:
                raise HTTPException(status_code=422, detail="enabled cannot be null")
            rule.enabled = rule_data.enabled

        if rule_data.trigger is not None or rule_data.enabled is not None:
            rule.next_run_at = (
                next_run_time(rule.trigger_conditions, datetime.now(UTC))
                if rule.enabled
                else None
            )
        rule.last_error = None
        session.commit()
        session.refresh(rule)
    except HTTPException:
        session.rollback()
        raise
    except SQLAlchemyError as error:
        session.rollback()
        _raise_database_error("update", error)
    return _response(rule)


@router.delete("/{automation_id}", status_code=204)
def delete_automation(
    automation_id: UUID,
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    access: Annotated[HomeAccess, Depends(require_non_guest)],
) -> Response:
    try:
        statement = select(AutomationRule).where(
            AutomationRule.id == automation_id,
            AutomationRule.home_id == access.home.id,
        )
        if access.role.value != "ADMIN":
            statement = statement.where(AutomationRule.owner_user_id == access.user.id)
        rule = session.scalar(statement)
        if rule is None:
            record_security_event(
                session,
                event_type="automation_permission_denied",
                severity="warning",
                source="/automations/{automation_id}",
                outcome="denied",
                user_id=access.user.id,
                home_id=access.home.id,
                request=request,
                metadata={"automation_id": str(automation_id), "method": "DELETE"},
            )
            raise HTTPException(status_code=404, detail="Automation not found")
        session.delete(rule)
        session.commit()
    except HTTPException:
        raise
    except SQLAlchemyError as error:
        session.rollback()
        _raise_database_error("deletion", error)
    return Response(status_code=204)
