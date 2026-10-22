import type { DeviceEvent, SimulatedDevice } from "./types";

const now = () => new Date().toISOString();

export function createDemoDevices(): SimulatedDevice[] {
  const createdAt = now();
  return [
    {
      id: "sim-living-room-light",
      name: "Ambient light",
      room: "Living room",
      device_type: "smart_light",
      status: "Ready",
      online: true,
      created_at: createdAt,
      updated_at: createdAt,
      simulated: true,
      power: true,
      speed: 0,
      sensor_readings: [],
    },
    {
      id: "sim-living-room-fan",
      name: "Ceiling fan",
      room: "Living room",
      device_type: "smart_fan",
      status: "Ready",
      online: true,
      created_at: createdAt,
      updated_at: createdAt,
      simulated: true,
      power: false,
      speed: 0,
      sensor_readings: [],
    },
    {
      id: "sim-bedroom-light",
      name: "Bedside light",
      room: "Bedroom",
      device_type: "smart_light",
      status: "Ready",
      online: true,
      created_at: createdAt,
      updated_at: createdAt,
      simulated: true,
      power: false,
      speed: 0,
      sensor_readings: [],
    },
    {
      id: "sim-kitchen-climate",
      name: "Climate sensor",
      room: "Kitchen",
      device_type: "temperature_sensor",
      status: "Monitoring",
      online: true,
      created_at: createdAt,
      updated_at: createdAt,
      simulated: true,
      power: false,
      speed: 0,
      sensor_readings: [
        {
          name: "Temperature",
          sensor_type: "temperature",
          reading: 21.4,
          unit: "°C",
          timestamp: createdAt,
        },
        {
          name: "Humidity",
          sensor_type: "humidity",
          reading: 46,
          unit: "%",
          timestamp: createdAt,
        },
      ],
    },
  ];
}

export function toggleSimulatedDevice(
  device: SimulatedDevice,
): { device: SimulatedDevice; event: DeviceEvent } {
  const power = !device.power;
  const updated = { ...device, power, status: power ? "On" : "Off", updated_at: now() };
  return {
    device: updated,
    event: {
      type: "device_state",
      device_id: device.id,
      status: updated.status,
      timestamp: updated.updated_at,
    },
  };
}

export function tickSimulatedSensors(
  devices: SimulatedDevice[],
  tick: number,
): { devices: SimulatedDevice[]; events: DeviceEvent[] } {
  const timestamp = now();
  const events: DeviceEvent[] = [];
  const updatedDevices = devices.map((device) => {
    if (!device.device_type.includes("sensor")) return device;
    const sensorReadings = device.sensor_readings.map((reading, index) => {
      const base = index === 0 ? 21.4 : 46;
      const variance = index === 0 ? 0.5 : 3;
      const value = Number((base + Math.sin(tick / 3 + index) * variance).toFixed(1));
      events.push({
        type: "simulator_sensor",
        device_id: device.id,
        name: reading.name,
        sensor_type: reading.sensor_type,
        reading: value,
        unit: reading.unit,
        timestamp,
      });
      return { ...reading, reading: value, timestamp };
    });
    return { ...device, sensor_readings: sensorReadings };
  });
  return { devices: updatedDevices, events };
}
