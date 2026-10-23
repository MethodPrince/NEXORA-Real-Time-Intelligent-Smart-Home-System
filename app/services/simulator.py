import json
from typing import Literal

from app.db.models import Device

SIMULATOR_STATUS_PREFIX = "simulator:"

DeviceKind = Literal["light", "fan", "curtain"]


class InvalidSimulatedCommandError(ValueError):
    pass


def device_kind(device_type: str) -> DeviceKind | None:
    normalized = device_type.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"light", "smart_light"}:
        return "light"
    if normalized in {"fan", "smart_fan"}:
        return "fan"
    if normalized in {"curtain", "smart_curtain"}:
        return "curtain"
    return None


def initial_state(kind: DeviceKind) -> dict[str, object]:
    if kind == "light":
        return {"power": False, "brightness": 100}
    if kind == "fan":
        return {"power": False, "speed": 0}
    return {"position": 0}


def encode_state(state: dict[str, object]) -> str:
    return SIMULATOR_STATUS_PREFIX + json.dumps(
        state,
        separators=(",", ":"),
        allow_nan=False,
    )


def simulated_state(device: Device) -> dict[str, object] | None:
    if not device.status.startswith(SIMULATOR_STATUS_PREFIX):
        return None
    kind = device_kind(device.device_type)
    if kind is None:
        return None
    try:
        state = json.loads(device.status.removeprefix(SIMULATOR_STATUS_PREFIX))
    except json.JSONDecodeError:
        return None
    if not isinstance(state, dict):
        return None
    if kind == "light":
        if (
            set(state) != {"power", "brightness"}
            or not isinstance(state["power"], bool)
            or type(state["brightness"]) is not int
            or not 0 <= state["brightness"] <= 100
        ):
            return None
    elif kind == "fan":
        if (
            set(state) != {"power", "speed"}
            or not isinstance(state["power"], bool)
            or type(state["speed"]) is not int
            or not 0 <= state["speed"] <= 3
        ):
            return None
    elif (
        set(state) != {"position"}
        or type(state["position"]) is not int
        or not 0 <= state["position"] <= 100
    ):
        return None
    return state


def is_simulated(device: Device) -> bool:
    return device.status.startswith(SIMULATOR_STATUS_PREFIX)


def display_status(kind: DeviceKind, state: dict[str, object]) -> str:
    if kind == "curtain":
        position = state["position"]
        if position == 0:
            return "Closed"
        if position == 100:
            return "Open"
        return "Partially open"
    return "On" if state["power"] else "Off"


def apply_command(
    kind: DeviceKind,
    current_state: dict[str, object],
    command: str,
    parameters: dict[str, object],
) -> dict[str, object]:
    next_state = dict(current_state)
    command = command.lower()

    if command in {"turn_on", "turn_off"}:
        _require_parameters(parameters, set())
        if kind == "curtain":
            next_state["position"] = 100 if command == "turn_on" else 0
        elif kind == "light":
            next_state["power"] = command == "turn_on"
        else:
            next_state["power"] = command == "turn_on"
            if command == "turn_on" and next_state["speed"] == 0:
                next_state["speed"] = 1
            elif command == "turn_off":
                next_state["speed"] = 0
    elif command == "set_power" and kind in {"light", "fan"}:
        _require_parameters(parameters, {"enabled"}, {"enabled"})
        enabled = parameters["enabled"]
        if not isinstance(enabled, bool):
            raise InvalidSimulatedCommandError("'enabled' must be a boolean")
        next_state["power"] = enabled
        if kind == "fan":
            next_state["speed"] = (
                max(1, int(next_state["speed"])) if enabled else 0
            )
    elif command == "set_brightness" and kind == "light":
        _require_parameters(parameters, {"brightness"}, {"brightness"})
        brightness = parameters["brightness"]
        if type(brightness) is not int or not 0 <= brightness <= 100:
            raise InvalidSimulatedCommandError(
                "'brightness' must be an integer from 0 to 100"
            )
        next_state["brightness"] = brightness
    elif command == "set_speed" and kind == "fan":
        _require_parameters(parameters, {"speed"}, {"speed"})
        speed = parameters["speed"]
        if type(speed) is not int or not 0 <= speed <= 3:
            raise InvalidSimulatedCommandError(
                "'speed' must be an integer from 0 to 3"
            )
        next_state["speed"] = speed
        next_state["power"] = speed > 0
    elif command in {"open", "close"} and kind == "curtain":
        _require_parameters(parameters, set())
        next_state["position"] = 100 if command == "open" else 0
    elif command == "set_position" and kind == "curtain":
        _require_parameters(parameters, {"position"}, {"position"})
        position = parameters["position"]
        if type(position) is not int or not 0 <= position <= 100:
            raise InvalidSimulatedCommandError(
                "'position' must be an integer from 0 to 100"
            )
        next_state["position"] = position
    else:
        raise InvalidSimulatedCommandError(
            f"Command '{command}' is not supported for this simulated device"
        )

    return next_state


def _require_parameters(
    parameters: dict[str, object],
    allowed: set[str],
    required: set[str] | None = None,
) -> None:
    required = required or set()
    unexpected = parameters.keys() - allowed
    missing = required - parameters.keys()
    if unexpected or missing:
        details = []
        if missing:
            details.append(f"missing parameter(s): {', '.join(sorted(missing))}")
        if unexpected:
            details.append(f"unexpected parameter(s): {', '.join(sorted(unexpected))}")
        raise InvalidSimulatedCommandError("; ".join(details))
