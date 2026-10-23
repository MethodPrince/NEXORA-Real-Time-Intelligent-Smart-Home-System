import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";

class MockSpeechRecognition {
  static instances: MockSpeechRecognition[] = [];
  onresult: ((event: {
    resultIndex: number;
    results: Array<{ 0: { transcript: string }; isFinal: boolean }>;
  }) => void) | null = null;
  onerror: (() => void) | null = null;
  onend: (() => void) | null = null;
  start = vi.fn();
  stop = vi.fn();

  constructor() {
    MockSpeechRecognition.instances.push(this);
  }
}

class MockWebSocket {
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  close = vi.fn();

  constructor(_url: string) {
    queueMicrotask(() => this.onopen?.());
  }
}

describe("NEXORA dashboard", () => {
  beforeEach(() => {
    MockSpeechRecognition.instances = [];
    vi.stubGlobal("SpeechRecognition", undefined);
    vi.stubGlobal("webkitSpeechRecognition", undefined);
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
        const url = String(input);
        return new Response(
          JSON.stringify(url.endsWith("/health")
            ? { status: "ok", service: "NEXORA", database: "connected" }
            : []),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("shows local demo devices and controls them without API writes", async () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: /good (morning|afternoon|evening)/i })).toBeInTheDocument();
    expect(screen.getAllByText("Ambient light").length).toBeGreaterThan(0);

    fireEvent.click(screen.getAllByRole("button", { name: "Turn off Ambient light" })[0]);

    await waitFor(() => expect(screen.getAllByText(/Powered off · local demo/).length).toBeGreaterThan(1));
    const fetcher = vi.mocked(fetch);
    expect(fetcher.mock.calls.some(([input]) => String(input).includes("/command"))).toBe(false);
  });

  it("updates the greeting from the local time while the dashboard is open", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 23, 8));
    render(<App />);

    expect(screen.getByRole("heading", { name: "Good morning, Prince" })).toBeInTheDocument();

    vi.setSystemTime(new Date(2026, 9, 23, 13));
    act(() => {
      vi.advanceTimersByTime(60_000);
    });

    expect(screen.getByRole("heading", { name: "Good afternoon, Prince" })).toBeInTheDocument();
  });

  it("sends commands for backend simulated devices and renders confirmed state", async () => {
    const device = {
      id: "backend-lamp",
      name: "Backend lamp",
      room: "Office",
      device_type: "smart_light",
      status: "Off",
      online: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      simulated: true,
      state: { power: false, brightness: 80 },
    };
    const fetcher = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/health")) {
        return new Response(
          JSON.stringify({ status: "ok", service: "NEXORA", database: "connected" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.endsWith("/command")) {
        return new Response(
          JSON.stringify({
            device_id: device.id,
            status: "applied",
            online: true,
            state: { power: true, brightness: 80 },
          }),
          { status: 202, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify([device]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetcher);

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Turn on Backend lamp" }));

    expect(await screen.findByText("On · brightness 80%")).toBeInTheDocument();
    expect(fetcher.mock.calls.some(([input, init]) => (
      String(input).endsWith("/devices/backend-lamp/command")
      && init?.method === "POST"
      && init.body === JSON.stringify({ command: "set_power", parameters: { enabled: true } })
    ))).toBe(true);
  });

  it("keeps local demo controls available when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new Error("Backend unavailable");
    }));

    render(<App />);

    expect(await screen.findByText("API offline")).toBeInTheDocument();
    expect(screen.getAllByText("Ambient light").length).toBeGreaterThan(0);
    fireEvent.click(screen.getAllByRole("button", { name: "Turn off Ambient light" })[0]);
    expect(screen.getAllByText(/Powered off · local demo/).length).toBeGreaterThan(0);
  });

  it("uses tap-to-talk voice input to issue a local device command", async () => {
    vi.stubGlobal("SpeechRecognition", MockSpeechRecognition);
    render(<App />);
    fireEvent.click(screen.getAllByRole("button", { name: "NORA assistant" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Start voice command" }));

    const recognition = MockSpeechRecognition.instances[0];
    expect(recognition.start).toHaveBeenCalledOnce();
    recognition.onresult?.({
      resultIndex: 0,
      results: [{ 0: { transcript: "Hey Method, switch on the living room light" }, isFinal: true }],
    });

    expect(await screen.findByText(/Ambient light turned on in the local demo/)).toBeInTheDocument();
  });

  it("responds when greeted as Method", async () => {
    render(<App />);
    fireEvent.click(screen.getAllByRole("button", { name: "NORA assistant" })[0]);

    fireEvent.change(screen.getByRole("textbox", { name: "Message NORA" }), {
      target: { value: "Hello Method" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("Hello! I’m listening. What would you like me to do?"))
      .toBeInTheDocument();
  });

  it("offers typed commands when browser speech recognition is unavailable", async () => {
    render(<App />);
    fireEvent.click(screen.getAllByRole("button", { name: "NORA assistant" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Start voice command" }));

    expect(await screen.findByText(/isn’t supported by this browser/i)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message NORA" })).toBeInTheDocument();
  });

  it("creates a backend schedule and can pause the saved automation", async () => {
    const device = {
      id: "scheduled-lamp",
      name: "Bedroom light",
      room: "Bedroom",
      device_type: "smart_light",
      status: "Off",
      online: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      simulated: true,
      state: { power: false, brightness: 100 },
    };
    const rule = {
      id: "weekday-lights",
      name: "Weekday lights",
      description: null,
      trigger: { type: "schedule", time: "07:30", timezone: "UTC", days: [0, 1, 2, 3, 4] },
      action: { device_id: device.id, command: "turn_on" },
      enabled: true,
      next_run_at: "2026-01-01T07:30:00Z",
      last_run_at: null,
      last_error: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/health")) {
        return new Response(JSON.stringify({ status: "ok", service: "NEXORA", database: "connected" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.endsWith("/devices")) {
        return new Response(JSON.stringify([device]), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.endsWith("/automations") && init?.method === "POST") {
        return new Response(JSON.stringify(rule), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      if (url.endsWith("/weekday-lights") && init?.method === "PATCH") {
        return new Response(JSON.stringify({ ...rule, enabled: false, next_run_at: null }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetcher);
    render(<App />);
    fireEvent.click(screen.getAllByRole("button", { name: "Automations" })[0]);

    expect(await screen.findByRole("heading", { name: "Create an automation" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Weekday lights" } });
    fireEvent.change(screen.getByLabelText("Time"), { target: { value: "07:30" } });
    fireEvent.click(screen.getByRole("button", { name: "Save schedule" }));

    expect(await screen.findByText("Weekday lights")).toBeInTheDocument();
    expect(fetcher.mock.calls.some(([input, init]) => (
      String(input).endsWith("/automations")
      && init?.method === "POST"
      && JSON.parse(String(init.body)).action.command === "turn_on"
      && JSON.parse(String(init.body)).trigger.days.length === 7
    ))).toBe(true);

    fireEvent.click(screen.getByRole("switch", { name: "Pause Weekday lights" }));
    expect(await screen.findByRole("switch", { name: "Enable Weekday lights" })).toHaveAttribute("aria-checked", "false");
  });
});
