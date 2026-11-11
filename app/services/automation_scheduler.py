import asyncio
import logging
from datetime import UTC
from datetime import datetime
from datetime import time
from datetime import timedelta
from zoneinfo import ZoneInfo
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.db.dependencies import device_recipients
from app.db.models import AutomationRule
from app.db.models import Device
from app.db.models import User
from app.db.session import get_engine
from app.services.mqtt import MQTTService
from app.services.mqtt import MQTTServiceUnavailableError
from app.services.simulator import InvalidSimulatedCommandError
from app.services.simulator import apply_command
from app.services.simulator import device_kind
from app.services.simulator import display_status
from app.services.simulator import encode_state
from app.services.simulator import is_simulated
from app.services.simulator import simulated_state
from app.websocket.connection_manager import connection_manager
from app.db.dependencies import user_can_access_device

logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 15


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def next_run_time(trigger: dict[str, object], now: datetime) -> datetime:
    zone = ZoneInfo(str(trigger["timezone"]))
    hour, minute = (int(part) for part in str(trigger["time"]).split(":"))
    days = {int(day) for day in trigger["days"]}
    local_now = _utc(now).astimezone(zone)
    for offset in range(8):
        candidate_date = local_now.date() + timedelta(days=offset)
        if candidate_date.weekday() not in days:
            continue
        candidate = datetime.combine(candidate_date, time(hour, minute), tzinfo=zone)
        if candidate > local_now:
            return candidate.astimezone(UTC)
    raise ValueError("Schedule must include at least one valid weekday")


def _device_command(device: Device, command: str) -> tuple[str, dict[str, object]]:
    kind = device_kind(device.device_type)
    if kind is None:
        raise ValueError("Automations support lights, fans, and curtains only")
    if kind == "curtain":
        if command not in {"open", "close"}:
            raise ValueError("Curtain automations must use open or close")
        return command, {}
    if command not in {"turn_on", "turn_off"}:
        raise ValueError("Light and fan automations must use turn_on or turn_off")
    return "set_power", {"enabled": command == "turn_on"}


def validate_device_action(device: Device, command: str) -> None:
    _device_command(device, command)


class AutomationScheduler:
    def __init__(
        self,
        mqtt_service: MQTTService,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._mqtt_service = mqtt_service
        self._session_factory = session_factory
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    def _session(self) -> Session:
        return self._session_factory() if self._session_factory else Session(get_engine())

    def start(self) -> None:
        if not get_settings().database_url:
            logger.error("Automation scheduler not started: DATABASE_URL is not configured")
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="nexora-automation-scheduler")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stopping.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                events = await asyncio.to_thread(self._run_due_rules)
                for event in events:
                    recipient_ids = event.pop("_recipient_user_ids", [])
                    home_id = event.pop("_home_id", None)
                    if recipient_ids and home_id:
                        await connection_manager.broadcast_to_home_users(
                            UUID(home_id),
                            (UUID(user_id) for user_id in recipient_ids),
                            event,
                        )
            except SQLAlchemyError:
                logger.exception("Automation scheduler database operation failed")
            except Exception:
                logger.exception("Automation scheduler iteration failed")
            try:
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=POLL_INTERVAL_SECONDS,
                )
            except TimeoutError:
                pass

    def _run_due_rules(self) -> list[dict[str, object]]:
        now = datetime.now(UTC)
        with self._session() as session:
            due_ids = list(
                session.scalars(
                    select(AutomationRule.id).where(
                        AutomationRule.enabled.is_(True),
                        AutomationRule.owner_user_id.is_not(None),
                        AutomationRule.next_run_at <= now,
                    )
                )
            )
            claimed: list[tuple[str, str, list[dict[str, object]], UUID, UUID]] = []
            for rule_id in due_ids:
                result = session.execute(
                    update(AutomationRule)
                    .where(
                        AutomationRule.id == rule_id,
                        AutomationRule.enabled.is_(True),
                        AutomationRule.owner_user_id.is_not(None),
                        AutomationRule.next_run_at <= now,
                    )
                    .values(
                        last_run_at=now,
                        next_run_at=now,
                    )
                    .returning(
                        AutomationRule.id,
                        AutomationRule.name,
                        AutomationRule.trigger_conditions,
                        AutomationRule.actions,
                        AutomationRule.owner_user_id,
                        AutomationRule.home_id,
                    )
                ).one_or_none()
                if (
                    result is None
                    or result.owner_user_id is None
                    or result.home_id is None
                ):
                    continue
                next_time = next_run_time(result.trigger_conditions, now)
                session.execute(
                    update(AutomationRule)
                    .where(AutomationRule.id == rule_id)
                    .values(next_run_at=next_time, last_error=None)
                )
                action = result.actions[0]
                claimed.append(
                    (
                        str(result.id),
                        result.name,
                        [action],
                        result.owner_user_id,
                        result.home_id,
                    )
                )
            session.commit()

        events: list[dict[str, object]] = []
        for rule_id, name, actions, owner_id, home_id in claimed:
            action = actions[0]
            try:
                event = self._execute_action(
                    rule_id,
                    name,
                    action,
                    owner_id,
                    home_id,
                )
            except (ValueError, InvalidSimulatedCommandError, MQTTServiceUnavailableError) as error:
                self._record_error(rule_id, str(error))
                logger.warning("Automation %s could not run: %s", rule_id, error)
                events.append({
                    "type": "automation_failed",
                    "_home_id": str(home_id),
                    "automation_id": rule_id,
                    "name": name,
                    "message": str(error),
                    "timestamp": datetime.now(UTC).isoformat(),
                })
            except SQLAlchemyError:
                self._record_error(rule_id, "Database operation unavailable")
                logger.exception("Automation %s database operation failed", rule_id)
                events.append({
                    "type": "automation_failed",
                    "_home_id": str(home_id),
                    "automation_id": rule_id,
                    "name": name,
                    "message": "Database operation unavailable",
                    "timestamp": datetime.now(UTC).isoformat(),
                })
            else:
                device_id = UUID(str(action["device_id"]))
                with self._session() as session:
                    device_home_id, recipient_ids = device_recipients(session, device_id)
                for item in event:
                    item["_recipient_user_ids"] = [
                        str(user_id) for user_id in recipient_ids
                    ]
                    item["_home_id"] = str(device_home_id or home_id)
                events.extend(event)
        return events

    def _execute_action(
        self,
        rule_id: str,
        name: str,
        action: dict[str, object],
        owner_id: UUID,
        home_id: UUID,
    ) -> list[dict[str, object]]:
        with self._session() as session:
            owner = session.get(User, owner_id)
            device = session.scalar(
                select(Device).where(
                    Device.id == UUID(str(action["device_id"])),
                    Device.home_id == home_id,
                )
            )
            if (
                owner is None
                or not owner.is_active
                or device is None
                or not user_can_access_device(
                    session,
                    owner,
                    UUID(str(action["device_id"])),
                    control=True,
                    home_id=home_id,
                )
            ):
                raise ValueError("Automation device is no longer permitted")
            if not device.online:
                raise ValueError(f"{device.name} is offline")
            command, parameters = _device_command(device, str(action["command"]))

            if is_simulated(device):
                kind = device_kind(device.device_type)
                state = simulated_state(device)
                if kind is None or state is None:
                    raise ValueError("Simulated device state is unavailable")
                state = apply_command(kind, state, command, parameters)
                device.status = encode_state(state)
                session.commit()
                session.refresh(device)
                status = display_status(kind, state)
                timestamp = _utc(device.updated_at).isoformat()
                return [
                    {
                        "type": "device_state",
                        "device_id": str(device.id),
                        "status": status,
                        "online": device.online,
                        "state": state,
                        "timestamp": timestamp,
                    },
                    {
                        "type": "automation_executed",
                        "automation_id": rule_id,
                        "name": name,
                        "device_id": str(device.id),
                        "timestamp": timestamp,
                    },
                ]

            topic = self._mqtt_service.publish_device_command(
                device.id,
                command,
                parameters,
            )
            return [{
                "type": "automation_executed",
                "automation_id": rule_id,
                "name": name,
                "device_id": str(device.id),
                "topic": topic,
                "timestamp": datetime.now(UTC).isoformat(),
            }]

    def _record_error(self, rule_id: str, message: str) -> None:
        from uuid import UUID

        with self._session() as session:
            session.execute(
                update(AutomationRule)
                .where(AutomationRule.id == UUID(rule_id))
                .values(last_error=message[:1000])
            )
            session.commit()
