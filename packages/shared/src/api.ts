import type { Device, DeviceCommand, DeviceCreate, DeviceUpdate } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class NexoraApi {
  constructor(
    private readonly baseUrl: string,
    private readonly fetcher: typeof fetch = fetch,
  ) {}

  async health(): Promise<{ status: string; service: string; database: string }> {
    return this.request("/health");
  }

  async listDevices(): Promise<Device[]> {
    return this.request("/devices");
  }

  async createDevice(device: DeviceCreate): Promise<Device> {
    return this.request("/devices", {
      method: "POST",
      body: JSON.stringify(device),
    });
  }

  async updateDevice(id: string, device: DeviceUpdate): Promise<Device> {
    return this.request(`/devices/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(device),
    });
  }

  async deleteDevice(id: string): Promise<void> {
    await this.request(`/devices/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  }

  async sendCommand(id: string, command: DeviceCommand): Promise<void> {
    await this.request(`/devices/${encodeURIComponent(id)}/command`, {
      method: "POST",
      body: JSON.stringify(command),
    });
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let response: Response;
    try {
      response = await this.fetcher(`${this.baseUrl}${path}`, {
        ...init,
        headers: {
          ...(init.body ? { "Content-Type": "application/json" } : {}),
          ...init.headers,
        },
      });
    } catch {
      throw new ApiError("Cannot reach the NEXORA backend.", 0);
    }

    if (!response.ok) {
      let detail = `Backend request failed (${response.status}).`;
      try {
        const body = (await response.json()) as { detail?: string };
        if (body.detail) detail = body.detail;
      } catch {
        // Keep the status-based message when the response is not JSON.
      }
      throw new ApiError(detail, response.status);
    }

    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }
}

export function websocketUrl(baseUrl: string, pageUrl: string): string {
  const page = new URL(pageUrl);
  const base = baseUrl ? new URL(baseUrl, page) : page;
  base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
  base.pathname = "/ws";
  base.search = "";
  base.hash = "";
  return base.toString();
}

export function isDeviceEvent(value: unknown): value is import("./types").DeviceEvent {
  if (!value || typeof value !== "object" || !("type" in value)) return false;
  return [
    "system_event",
    "device_state",
    "device_sensor",
    "device_availability",
    "device_command",
    "simulator_sensor",
  ].includes(String((value as { type: unknown }).type));
}
