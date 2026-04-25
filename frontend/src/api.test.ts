import { describe, expect, it } from "vitest";

import { resolveApiBase } from "./api";

describe("resolveApiBase", () => {
  it("uses the backend dev port for local frontend hosts", () => {
    expect(resolveApiBase(undefined, { origin: "http://127.0.0.1:5173" })).toBe("http://127.0.0.1:8000");
  });

  it("uses same-origin when the app is served from the backend domain", () => {
    expect(resolveApiBase(undefined, { origin: "https://app.sgroute.com" })).toBe("https://app.sgroute.com");
  });

  it("preserves an explicit API base and strips a trailing slash", () => {
    expect(resolveApiBase("http://localhost:9000/", { origin: "http://127.0.0.1:5173" })).toBe("http://localhost:9000");
  });

  it("falls back to localhost when no browser location is available", () => {
    expect(resolveApiBase()).toBe("http://localhost:8000");
  });
});
