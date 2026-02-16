import { describe, expect, it } from "vitest";

import { checkCoordinate, normalizeLatLng } from "./geo";

describe("normalizeLatLng", () => {
  it("returns [lat, lon] in leaflet order", () => {
    expect(normalizeLatLng({ lat: "1.3001", lon: "103.8555" })).toEqual([1.3001, 103.8555]);
  });

  it("auto-corrects obvious swapped input", () => {
    expect(normalizeLatLng({ lat: 103.8555, lon: 1.3001 })).toEqual([1.3001, 103.8555]);
  });

  it("rejects out-of-range coordinates", () => {
    expect(() => normalizeLatLng({ lat: 120, lon: 240 })).toThrow("WGS84 bounds");
  });
});

describe("checkCoordinate", () => {
  it("flags singapore bounds warning without failing validity", () => {
    const result = checkCoordinate({ lat: 40.7128, lon: -74.006 });
    expect(result.isValid).toBe(true);
    expect(result.warnings).toContain("OUTSIDE_SINGAPORE");
  });
});

