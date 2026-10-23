import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    vi.unstubAllGlobals();
  });

  it("shows local demo devices and controls them without API writes", async () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: /good evening/i })).toBeInTheDocument();
    expect(screen.getAllByText("Ambient light").length).toBeGreaterThan(0);

    fireEvent.click(screen.getAllByRole("button", { name: "Turn off Ambient light" })[0]);

    await waitFor(() => expect(screen.getAllByText(/Powered off · local demo/).length).toBeGreaterThan(1));
    const fetcher = vi.mocked(fetch);
    expect(fetcher.mock.calls.some(([input]) => String(input).includes("/command"))).toBe(false);
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
      results: [{ 0: { transcript: "switch on the living room light" }, isFinal: true }],
    });

    expect(await screen.findByText(/Ambient light turned on in the local demo/)).toBeInTheDocument();
  });

  it("offers typed commands when browser speech recognition is unavailable", async () => {
    render(<App />);
    fireEvent.click(screen.getAllByRole("button", { name: "NORA assistant" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Start voice command" }));

    expect(await screen.findByText(/isn’t supported by this browser/i)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message NORA" })).toBeInTheDocument();
  });

  it("labels automations as a preview instead of inventing a backend API", async () => {
    render(<App />);
    fireEvent.click(screen.getAllByRole("button", { name: "Automations" })[0]);

    expect(await screen.findByText(/no rules api or execution engine/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create rule/i })).toBeDisabled();
  });
});
