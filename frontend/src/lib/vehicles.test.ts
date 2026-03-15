import { describe, expect, it } from "vitest";

import { vehicleLabel, vehicleNumber } from "./vehicles";

describe("vehicle helpers", () => {
  it("renders user-facing vehicle numbers starting at one", () => {
    expect(vehicleNumber(0)).toBe(1);
    expect(vehicleNumber(1)).toBe(2);
    expect(vehicleLabel(0)).toBe("Vehicle 1");
    expect(vehicleLabel(1)).toBe("Vehicle 2");
  });
});
