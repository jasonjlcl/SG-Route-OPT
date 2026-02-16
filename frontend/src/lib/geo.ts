const SG_BOUNDS = {
  minLat: 1.13,
  maxLat: 1.48,
  minLon: 103.59,
  maxLon: 104.1,
};

export type LatLonInput = {
  lat: number | string | null | undefined;
  lon: number | string | null | undefined;
};

export type CoordinateWarningCode = "SWAPPED_INPUT" | "OUTSIDE_SINGAPORE";

export type CoordinateCheck = {
  isValid: boolean;
  point: [number, number] | null;
  warnings: CoordinateWarningCode[];
};

function toFinite(value: number | string | null | undefined): number {
  if (value === null || value === undefined || value === "") {
    throw new Error("Missing coordinate");
  }
  const parsed = typeof value === "number" ? value : Number(String(value).trim());
  if (!Number.isFinite(parsed)) {
    throw new Error("Coordinate must be finite");
  }
  return parsed;
}

function shouldSwap(lat: number, lon: number): boolean {
  return Math.abs(lat) > 90 && Math.abs(lon) <= 90 && Math.abs(lat) <= 180;
}

export function normalizeLatLng(input: LatLonInput): [number, number] {
  let lat = toFinite(input.lat);
  let lon = toFinite(input.lon);

  if (shouldSwap(lat, lon)) {
    [lat, lon] = [lon, lat];
  }

  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    throw new Error("Coordinate is outside WGS84 bounds");
  }
  return [lat, lon];
}

export function checkCoordinate(input: LatLonInput): CoordinateCheck {
  const rawLat = input.lat;
  const rawLon = input.lon;
  const warnings: CoordinateWarningCode[] = [];

  let rawLatNum: number | null = null;
  let rawLonNum: number | null = null;
  try {
    rawLatNum = toFinite(rawLat);
    rawLonNum = toFinite(rawLon);
  } catch {
    return { isValid: false, point: null, warnings };
  }

  if (shouldSwap(rawLatNum, rawLonNum)) {
    warnings.push("SWAPPED_INPUT");
  }

  try {
    const [lat, lon] = normalizeLatLng(input);
    const outsideSingapore =
      lat < SG_BOUNDS.minLat || lat > SG_BOUNDS.maxLat || lon < SG_BOUNDS.minLon || lon > SG_BOUNDS.maxLon;
    if (outsideSingapore) {
      warnings.push("OUTSIDE_SINGAPORE");
    }
    return { isValid: true, point: [lat, lon], warnings };
  } catch {
    return { isValid: false, point: null, warnings };
  }
}

