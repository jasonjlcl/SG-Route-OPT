import { describe, expect, it } from "vitest";

import { resolveApiBase } from "./api";

describe("resolveApiBase", () => {
  it("uses the current browser hostname when no explicit API base is configured", () => {
    expect(resolveApiBase(undefined, { origin: "http://127.0.0.1:5173" })).toBe("http://127.0.0.1:8000");
  });

  it("preserves an explicit API base and strips a trailing slash", () => {
    expect(resolveApiBase("http://localhost:9000/", { origin: "http://127.0.0.1:5173" })).toBe("http://localhost:9000");
  });

  it("falls back to localhost when no browser location is available", () => {
    expect(resolveApiBase()).toBe("http://localhost:8000");
  });
});
