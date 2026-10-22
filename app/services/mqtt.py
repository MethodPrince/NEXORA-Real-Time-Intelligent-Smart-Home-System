import asyncio
import json
import logging
from datetime import datetime
from datetime import timezone
from uuid import UUID

import paho.mqtt.client as mqtt
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Device
from app.db.models import Sensor
from app.db.session import get_engine
from app.websocket.connection_manager import connection_manager

logger = logging.getLogger(__name__)

DEVICE_TOPIC_PREFIX = "nexora/devices"
INBOUND_TOPICS = (
    f"{DEVICE_TOPIC_PREFIX}/+/state",
    f"{DEVICE_TOPIC_PREFIX}/+/sensor",
    f"{DEVICE_TOPIC_PREFIX}/+/availability",
)


class MQTTServiceUnavailableError(RuntimeError):
    pass


class DeviceStateMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: str = Field(min_length=1, max_length=100)


class DeviceSensorMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    sensor_type: str = Field(min_length=1, max_length=100)
    reading: float | None = Field(default=None, allow_inf_nan=False)
    unit: str | None = Field(default=None, max_length=40)


class MQTTService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
            protocol=mqtt.MQTTv311,
        )
        if settings.mqtt_username is not None:
            self._client.username_pw_set(
                settings.mqtt_username,
                settings.mqtt_password,
            )
        if settings.mqtt_tls_enabled:
            self._client.tls_set()

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._connected = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[tuple[str, bytes]] | None = None
        self._worker_task: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        if not self._settings.mqtt_enabled:
            logger.info("MQTT integration is disabled")
            return

        self._loop = asyncio.get_running_loop()
        result = self._client.connect_async(
            self._settings.mqtt_host,
            self._settings.mqtt_port,
            self._settings.mqtt_keepalive,
        )
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise MQTTServiceUnavailableError(
                f"Unable to initialize MQTT connection (code {result})"
            )
        self._client.loop_start()

    async def stop(self) -> None:
        if self._settings.mqtt_enabled:
            try:
                self._client.disconnect()
            finally:
                await asyncio.to_thread(self._client.loop_stop)
                self._connected = False
        if self._queue is not None:
            await self._queue.join()
        if self._worker_task is not None:
            await self._worker_task

    def publish_device_command(
        self,
        device_id: UUID,
        command: str,
        parameters: dict[str, object],
    ) -> str:
        if not self._settings.mqtt_enabled or not self._connected:
            raise MQTTServiceUnavailableError("MQTT broker is not connected")

        topic = f"{DEVICE_TOPIC_PREFIX}/{device_id}/command"
        payload = json.dumps(
            {"command": command, "parameters": parameters},
            separators=(",", ":"),
            allow_nan=False,
        )
        info = self._client.publish(topic, payload, qos=1)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise MQTTServiceUnavailableError(
                f"Unable to publish MQTT command (code {info.rc})"
            )
        return topic

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: object,
        _flags: object,
        reason_code: object,
        _properties: object,
    ) -> None:
        if getattr(reason_code, "is_failure", False):
            self._connected = False
            logger.error("MQTT broker rejected connection: %s", reason_code)
            return

        self._connected = True
        logger.info("Connected to MQTT broker")
        for topic in INBOUND_TOPICS:
            result, _message_id = client.subscribe(topic, qos=1)
            if result != mqtt.MQTT_ERR_SUCCESS:
                logger.error("Unable to subscribe to MQTT topic %s", topic)

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: object,
        _disconnect_flags: object,
        reason_code: object,
        _properties: object,
    ) -> None:
        self._connected = False
        if getattr(reason_code, "is_failure", False):
            logger.warning("MQTT connection lost: %s", reason_code)
        else:
            logger.info("Disconnected from MQTT broker")

    def _on_message(
        self,
        _client: mqtt.Client,
        _userdata: object,
        message: mqtt.MQTTMessage,
    ) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            logger.warning("Ignoring MQTT message while backend event loop is stopped")
            return
        try:
            loop.call_soon_threadsafe(
                self._schedule_message,
                message.topic,
                bytes(message.payload),
            )
        except RuntimeError:
            logger.warning("Ignoring MQTT message after backend shutdown")

    def _schedule_message(self, topic: str, payload: bytes) -> None:
        if self._queue is None:
            self._queue = asyncio.Queue()
        self._queue.put_nowait((topic, payload))
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._drain_messages())
            self._worker_task.add_done_callback(self._message_task_done)

    async def _drain_messages(self) -> None:
        assert self._queue is not None
        while not self._queue.empty():
            topic, payload = await self._queue.get()
            try:
                await self._process_message(topic, payload)
            except Exception:
                logger.exception("MQTT message processing failed")
            finally:
                self._queue.task_done()

    def _message_task_done(self, task: asyncio.Task[None]) -> None:
        if self._worker_task is task:
            self._worker_task = None
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "MQTT message queue failed",
                exc_info=(type(error), error, error.__traceback__),
            )

    async def _process_message(self, topic: str, payload: bytes) -> None:
        try:
            device_id, message_type = self._parse_topic(topic)
            message_text = payload.decode("utf-8")
            if message_type == "availability":
                availability = message_text.strip().lower()
                if availability not in {"online", "offline"}:
                    raise ValueError("availability must be online or offline")
                event = await asyncio.to_thread(
                    self._persist_availability,
                    device_id,
                    availability == "online",
                )
            elif message_type == "state":
                state = DeviceStateMessage.model_validate_json(message_text)
                event = await asyncio.to_thread(
                    self._persist_state,
                    device_id,
                    state,
                )
            else:
                sensor = DeviceSensorMessage.model_validate_json(message_text)
                event = await asyncio.to_thread(
                    self._persist_sensor,
                    device_id,
                    sensor,
                )
        except (UnicodeDecodeError, ValueError, ValidationError) as error:
            logger.warning("Ignoring invalid MQTT message on %s: %s", topic, error)
            return

        if event is not None:
            await connection_manager.broadcast(event)

    @staticmethod
    def _parse_topic(topic: str) -> tuple[UUID, str]:
        parts = topic.split("/")
        if (
            len(parts) != 4
            or parts[0] != "nexora"
            or parts[1] != "devices"
            or parts[3] not in {"state", "sensor", "availability"}
        ):
            raise ValueError("unrecognized MQTT topic")
        return UUID(parts[2]), parts[3]

    @staticmethod
    def _persist_availability(
        device_id: UUID,
        online: bool,
    ) -> dict[str, object] | None:
        try:
            with Session(get_engine()) as session:
                device = session.get(Device, device_id)
                if device is None:
                    logger.warning("Ignoring MQTT message for unknown device %s", device_id)
                    return None
                device.online = online
                session.commit()
        except SQLAlchemyError:
            logger.exception("Unable to save device availability from MQTT")
            raise
        return {
            "type": "device_availability",
            "device_id": str(device_id),
            "online": online,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _persist_state(
        device_id: UUID,
        state: DeviceStateMessage,
    ) -> dict[str, object] | None:
        try:
            with Session(get_engine()) as session:
                device = session.get(Device, device_id)
                if device is None:
                    logger.warning("Ignoring MQTT message for unknown device %s", device_id)
                    return None
                device.status = state.status
                session.commit()
        except SQLAlchemyError:
            logger.exception("Unable to save device state from MQTT")
            raise
        return {
            "type": "device_state",
            "device_id": str(device_id),
            "status": state.status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _persist_sensor(
        device_id: UUID,
        sensor_data: DeviceSensorMessage,
    ) -> dict[str, object] | None:
        try:
            with Session(get_engine()) as session:
                device = session.get(Device, device_id)
                if device is None:
                    logger.warning("Ignoring MQTT message for unknown device %s", device_id)
                    return None
                sensor = Sensor(
                    device_id=device_id,
                    name=sensor_data.name,
                    sensor_type=sensor_data.sensor_type,
                    reading=sensor_data.reading,
                    unit=sensor_data.unit,
                )
                session.add(sensor)
                session.commit()
                sensor_id = sensor.id
                timestamp = sensor.timestamp
        except SQLAlchemyError:
            logger.exception("Unable to save sensor reading from MQTT")
            raise
        return {
            "type": "device_sensor",
            "device_id": str(device_id),
            "sensor_id": str(sensor_id),
            "name": sensor_data.name,
            "sensor_type": sensor_data.sensor_type,
            "reading": sensor_data.reading,
            "unit": sensor_data.unit,
            "timestamp": timestamp.isoformat(),
        }
