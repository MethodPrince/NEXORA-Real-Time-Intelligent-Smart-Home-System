import { describe, expect, it, vi } from "vitest";
import { NexoraApi, websocketUrl } from "./api";
import { createDemoDevices, tickSimulatedSensors, toggleSimulatedDevice } from "./simulator";

describe("shared API contract", () => {
  it("uses only existing device endpoints", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const status = init?.method === "DELETE" ? 204 : 200;
      return new Response(
        status === 204 ? null : JSON.stringify({ id: "device-1", name: "Lamp" }),
        { status, headers: { "Content-Type": "application/json" } },
      );
    });
    const api = new NexoraApi("http://backend.test", fetcher as typeof fetch);
    await api.listDevices();
    await api.createDevice({ name: "Lamp", device_type: "smart_light" });
    await api.updateDevice("device-1", { room: "Living room" });
    await api.deleteDevice("device-1");
    await api.sendCommand("device-1", { command: "set_power", parameters: { enabled: true } });

    expect(fetcher.mock.calls.map(([url, init]) => [String(url), init?.method ?? "GET"])).toEqual([
      ["http://backend.test/devices", "GET"],
      ["http://backend.test/devices", "POST"],
      ["http://backend.test/devices/device-1", "PATCH"],
      ["http://backend.test/devices/device-1", "DELETE"],
      ["http://backend.test/devices/device-1/command", "POST"],
    ]);
  });

  it("surfaces existing broker-unavailable errors without hiding them", async () => {
    const fetcher = vi.fn(async () => new Response(
      JSON.stringify({ detail: "MQTT broker is unavailable" }),
      { status: 503, headers: { "Content-Type": "application/json" } },
    ));
    const api = new NexoraApi("", fetcher as typeof fetch);

    await expect(api.sendCommand("device-1", { command: "set_power" }))
      .rejects.toMatchObject({ status: 503, message: "MQTT broker is unavailable" });
  });

  it("maps HTTP endpoints to WebSocket URLs", () => {
    expect(websocketUrl("", "http://localhost:5173/")).toBe("ws://localhost:5173/ws");
    expect(websocketUrl("https://api.example.test", "http://localhost:5173/"))
      .toBe("wss://api.example.test/ws");
  });
});

describe("local simulator", () => {
  it("changes simulated actuators locally and produces synthetic sensor updates", () => {
    const devices = createDemoDevices();
    const light = devices.find((device) => device.id === "sim-living-room-light");
    const sensor = devices.find((device) => device.id === "sim-kitchen-climate");
    expect(light).toBeDefined();
    expect(sensor).toBeDefined();

    const toggled = toggleSimulatedDevice(light!);
    const tick = tickSimulatedSensors([sensor!], 1);

    expect(toggled.device.power).toBe(false);
    expect(toggled.event.device_id).toMatch(/^sim-/);
    expect(tick.devices[0].sensor_readings[0].reading).not.toBe(21.4);
    expect(tick.events[0].type).toBe("simulator_sensor");
  });
});
