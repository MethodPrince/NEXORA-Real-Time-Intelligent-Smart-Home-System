import type {
  Device,
  DeviceCommand,
  DeviceCommandAccepted,
  DeviceCreate,
  DeviceUpdate,
  AutomationCreate,
  AutomationRule,
  AutomationUpdate,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface AuthResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: {
    id: string;
    name: string;
    email: string;
    role: UserRole;
    is_active: boolean;
    is_platform_admin: boolean;
  };
}

export type UserRole = "ADMIN" | "STANDARD_USER" | "GUEST";

export interface HomeInfo {
  id: string;
  name: string;
  role: UserRole;
}

export interface AdminUser {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  is_active: boolean;
}

export interface DeviceGrant {
  device_id: string;
  can_control: boolean;
  name?: string;
  room?: string | null;
  device_type?: string;
}

export interface AdminSecuritySettings {
  access_token_expire_minutes: number;
  cors_origins: string[];
  registration_enabled: boolean;
  admin_bootstrap_available: boolean;
  jwt_secret_configured: boolean;
}

export interface AdminActivityLog {
  id: string;
  user_id: string | null;
  device_id: string | null;
  source: string;
  event: string;
  action: string | null;
  result: string | null;
  timestamp: string;
}

export interface ActivityRecord {
  id: string;
  user_id?: string | null;
  device_id: string | null;
  source: string;
  event: string;
  action: string | null;
  result: string | null;
  timestamp: string;
}

export interface AdminSecurityEvent {
  id: string;
  user_id: string | null;
  home_id: string | null;
  event_type: string;
  severity: string;
  source: string;
  source_ip: string | null;
  outcome: string;
  metadata: Record<string, unknown>;
  response: string | null;
  timestamp: string;
}

export function websocketProtocols(accessToken: string): string[] {
  return ["nexora", `bearer.${accessToken}`];
}

export class NexoraApi {
  private accessToken: string | null = null;
  private homeId: string | null = null;

  constructor(
    private readonly baseUrl: string,
    private readonly fetcher?: typeof fetch,
  ) {}

  setAccessToken(token: string | null): void {
    this.accessToken = token;
  }

  setHomeId(homeId: string | null): void {
    this.homeId = homeId;
  }

  getAccessToken(): string | null {
    return this.accessToken;
  }

  async listHomes(): Promise<HomeInfo[]> {
    return this.request("/homes");
  }

  async createHome(name: string): Promise<HomeInfo> {
    return this.request("/homes", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  }

  async register(input: { name: string; email: string; password: string }): Promise<AuthResponse> {
    return this.request("/auth/register", {
      method: "POST",
      body: JSON.stringify(input),
    });
  }

  async login(input: { email: string; password: string }): Promise<AuthResponse> {
    return this.request("/auth/login", {
      method: "POST",
      body: JSON.stringify(input),
    });
  }

  async listUsers(): Promise<AdminUser[]> {
    return this.request("/admin/users");
  }

  async getAdminSecuritySettings(): Promise<AdminSecuritySettings> {
    return this.request("/admin/security-settings");
  }

  async updateAdminSecuritySettings(
    input: Pick<AdminSecuritySettings, "registration_enabled">,
  ): Promise<AdminSecuritySettings> {
    return this.request("/admin/security-settings", {
      method: "PATCH",
      body: JSON.stringify(input),
    });
  }

  async listAllActivity(): Promise<AdminActivityLog[]> {
    return this.request("/admin/activity");
  }

  async listActivity(): Promise<ActivityRecord[]> {
    return this.request("/activity");
  }

  async listSecurityEvents(): Promise<AdminSecurityEvent[]> {
    return this.request("/admin/security-events");
  }

  async createUser(input: {
    name: string;
    email: string;
    password: string;
    role: UserRole;
  }): Promise<AdminUser> {
    return this.request("/admin/users", {
      method: "POST",
      body: JSON.stringify(input),
    });
  }

  async updateUser(id: string, input: Partial<Pick<AdminUser, "role" | "is_active">>): Promise<AdminUser> {
    return this.request(`/admin/users/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    });
  }

  async deleteUser(id: string): Promise<void> {
    await this.request(`/admin/users/${encodeURIComponent(id)}`, { method: "DELETE" });
  }

  async listDeviceAccess(id: string): Promise<DeviceGrant[]> {
    return this.request(`/admin/users/${encodeURIComponent(id)}/device-access`);
  }

  async replaceDeviceAccess(
    id: string,
    grants: Pick<DeviceGrant, "device_id" | "can_control">[],
  ): Promise<DeviceGrant[]> {
    return this.request(`/admin/users/${encodeURIComponent(id)}/device-access`, {
      method: "PUT",
      body: JSON.stringify({ grants }),
    });
  }

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

  async sendCommand(id: string, command: DeviceCommand): Promise<DeviceCommandAccepted> {
    return this.request(`/devices/${encodeURIComponent(id)}/command`, {
      method: "POST",
      body: JSON.stringify(command),
    });
  }

  async listAutomations(): Promise<AutomationRule[]> {
    return this.request("/automations");
  }

  async createAutomation(automation: AutomationCreate): Promise<AutomationRule> {
    return this.request("/automations", {
      method: "POST",
      body: JSON.stringify(automation),
    });
  }

  async updateAutomation(id: string, automation: AutomationUpdate): Promise<AutomationRule> {
    return this.request(`/automations/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(automation),
    });
  }

  async deleteAutomation(id: string): Promise<void> {
    await this.request(`/automations/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let response: Response;
    try {
      response = await (this.fetcher ?? fetch)(`${this.baseUrl}${path}`, {
        ...init,
        headers: {
          ...(this.homeId ? { "X-Home-ID": this.homeId } : {}),
          ...(init.body ? { "Content-Type": "application/json" } : {}),
          ...(this.accessToken ? { Authorization: `Bearer ${this.accessToken}` } : {}),
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

export function websocketUrl(baseUrl: string, pageUrl: string, homeId?: string): string {
  const page = new URL(pageUrl);
  const base = baseUrl ? new URL(baseUrl, page) : page;
  base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
  base.pathname = "/ws";
  base.search = homeId ? new URLSearchParams({ home_id: homeId }).toString() : "";
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
