export function vehicleNumber(vehicleIdx: number): number {
  return Number(vehicleIdx) + 1;
}

export function vehicleLabel(vehicleIdx: number): string {
  return `Vehicle ${vehicleNumber(vehicleIdx)}`;
}
