import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";

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
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
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
    vi.unstubAllGlobals();
  });

  it("shows local demo devices and controls them without API writes", async () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: /good evening/i })).toBeInTheDocument();
    expect(screen.getByText("Ambient light")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Turn off Ambient light" }));

    await waitFor(() => expect(screen.getAllByText("Powered off").length).toBeGreaterThan(1));
    const fetcher = vi.mocked(fetch);
    expect(fetcher.mock.calls.some(([input]) => String(input).includes("/command"))).toBe(false);
  });

  it("labels automations as a preview instead of inventing a backend API", async () => {
    render(<App />);
    fireEvent.click(screen.getAllByRole("button", { name: "Automations" })[0]);

    expect(await screen.findByText(/no rules api or execution engine/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create rule/i })).toBeDisabled();
  });
});
