import axios from "axios";
import type { PlanDetails, StopItem, UploadResponse } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const api = axios.create({
  baseURL: API_BASE,
});

export async function uploadDataset(file: File, excludeInvalid: boolean): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("exclude_invalid", String(excludeInvalid));

  const { data } = await api.post<UploadResponse>("/api/v1/datasets/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function getDataset(datasetId: number) {
  const { data } = await api.get(`/api/v1/datasets/${datasetId}`);
  return data;
}

export async function getStops(datasetId: number, status?: string) {
  const params = status ? { status } : undefined;
  const { data } = await api.get<{ items: StopItem[]; total: number }>(`/api/v1/datasets/${datasetId}/stops`, { params });
  return data;
}

export async function runGeocoding(datasetId: number, failedOnly = false) {
  const { data } = await api.post(`/api/v1/datasets/${datasetId}/geocode`, null, {
    params: { failed_only: failedOnly },
  });
  return data;
}

export async function manualResolveStop(stopId: number, payload: Record<string, string | number | null>) {
  const { data } = await api.post(`/api/v1/stops/${stopId}/geocode/manual`, payload);
  return data;
}

export async function optimizeDataset(datasetId: number, payload: unknown) {
  const { data } = await api.post(`/api/v1/datasets/${datasetId}/optimize`, payload);
  return data;
}

export async function getPlan(planId: number): Promise<PlanDetails> {
  const { data } = await api.get<PlanDetails>(`/api/v1/plans/${planId}`);
  return data;
}

export function getValidationErrorLogUrl(datasetId: number): string {
  return `${API_BASE}/api/v1/datasets/${datasetId}/error-log`;
}

export function getExportUrl(
  planId: number,
  format: "csv" | "pdf",
  options?: { profile?: "planner" | "driver"; vehicleIdx?: number | null }
): string {
  const params = new URLSearchParams({ format });
  if (options?.profile) params.set("profile", options.profile);
  if (typeof options?.vehicleIdx === "number") params.set("vehicle_idx", String(options.vehicleIdx));
  return `${API_BASE}/api/v1/plans/${planId}/export?${params.toString()}`;
}

export function getDriverCsvUrl(planId: number): string {
  return `${API_BASE}/api/v1/plans/${planId}/export/driver-csv`;
}

export function getMapSnapshotUrl(planId: number, vehicleIdx?: number | null): string {
  const params = new URLSearchParams();
  if (typeof vehicleIdx === "number") params.set("vehicle_idx", String(vehicleIdx));
  const query = params.toString();
  return `${API_BASE}/api/v1/plans/${planId}/map-snapshot${query ? `?${query}` : ""}`;
}
