export interface Device {
  id: string;
  name: string;
  room: string | null;
  device_type: string;
  status: string;
  online: boolean;
  created_at: string;
  updated_at: string;
  simulated?: boolean;
  state?: SimulatedDeviceState | null;
}

export interface DeviceCreate {
  name: string;
  room?: string | null;
  device_type: string;
  status?: string;
  online?: boolean;
  simulated?: boolean;
}

export interface DeviceUpdate {
  name?: string;
  room?: string | null;
  device_type?: string;
  status?: string;
  online?: boolean;
}

export interface DeviceCommand {
  command: string;
  parameters?: Record<string, unknown>;
}

export interface DeviceCommandAccepted {
  device_id: string;
  topic?: string;
  status: string;
  online?: boolean;
  state?: SimulatedDeviceState;
}

export interface SimulatedDeviceState {
  power?: boolean;
  brightness?: number;
  speed?: number;
  position?: number;
  open?: boolean;
}

export interface SensorReading {
  name: string;
  sensor_type: string;
  reading: number | null;
  unit: string | null;
  timestamp: string;
}

export interface DeviceEvent {
  type:
    | "system_event"
    | "device_state"
    | "device_sensor"
    | "device_availability"
    | "device_command"
    | "simulator_sensor";
  source?: string;
  device_id?: string;
  message?: string;
  status?: string;
  online?: boolean;
  state?: SimulatedDeviceState;
  name?: string;
  sensor_type?: string;
  reading?: number | null;
  unit?: string | null;
  timestamp?: string;
}

export interface SimulatedDevice extends Device {
  simulated: true;
  demo: true;
  power: boolean;
  speed: number;
  sensor_readings: SensorReading[];
}

export interface ActivityItem {
  id: string;
  title: string;
  detail: string;
  timestamp: string;
  kind: "device" | "sensor" | "security" | "system";
}
