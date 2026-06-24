import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

describe("getApiBase origin routing", () => {
  const originalLocation = globalThis.window?.location;

  beforeEach(() => {
    vi.stubEnv("VITE_API_BASE", "https://upcountry-latter-gem.ngrok-free.dev");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    if (originalLocation) {
      Object.defineProperty(globalThis, "location", { value: originalLocation, configurable: true });
    }
  });

  it("uses Vite proxy on PC localhost when VITE_API_BASE is ngrok", async () => {
    Object.defineProperty(globalThis, "location", {
      value: { origin: "http://127.0.0.1:5173" },
      configurable: true,
    });
    vi.resetModules();
    const { getApiBase, apiUrl } = await import("./config");
    expect(getApiBase()).toBe("");
    expect(apiUrl("/api/shell/poll")).toBe("/api/shell/poll");
  });

  it("uses ngrok base when page is opened on the Quest HTTPS URL", async () => {
    Object.defineProperty(globalThis, "location", {
      value: { origin: "https://upcountry-latter-gem.ngrok-free.dev" },
      configurable: true,
    });
    vi.resetModules();
    const { getApiBase, apiUrl } = await import("./config");
    expect(getApiBase()).toBe("https://upcountry-latter-gem.ngrok-free.dev");
    expect(apiUrl("/api/shell/poll")).toBe(
      "https://upcountry-latter-gem.ngrok-free.dev/api/shell/poll",
    );
  });
});
