import axios from "axios";
import type { DatasetSummary, JobAccepted, JobStatus, PlanDetails, StopItem, UploadResponse } from "./types";

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

export async function getDataset(datasetId: number): Promise<DatasetSummary> {
  const { data } = await api.get<DatasetSummary>(`/api/v1/datasets/${datasetId}`);
  return data;
}

export async function getStops(datasetId: number, status?: string) {
  const params = status ? { status } : undefined;
  const { data } = await api.get<{ items: StopItem[]; total: number }>(`/api/v1/datasets/${datasetId}/stops`, { params });
  return data;
}

export async function runGeocoding(datasetId: number, failedOnly = false, forceAll = false) {
  const { data } = await api.post<JobAccepted>(`/api/v1/datasets/${datasetId}/geocode`, null, {
    params: { failed_only: failedOnly, force_all: forceAll },
  });
  return data;
}

export async function manualResolveStop(stopId: number, payload: Record<string, string | number | null>) {
  const { data } = await api.post(`/api/v1/stops/${stopId}/geocode/manual`, payload);
  return data;
}

export async function optimizeDataset(datasetId: number, payload: unknown) {
  const { data } = await api.post<JobAccepted>(`/api/v1/datasets/${datasetId}/optimize`, payload);
  return data;
}

export async function getPlan(planId: number): Promise<PlanDetails> {
  const { data } = await api.get<PlanDetails>(`/api/v1/plans/${planId}`);
  return data;
}

export async function resequenceRoute(
  planId: number,
  routeId: number,
  payload: { ordered_stop_ids: number[]; depart_time_iso?: string | null; apply?: boolean }
) {
  const { data } = await api.post(`/api/v1/plans/${planId}/routes/${routeId}/resequence`, payload);
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

export function getMapPngUrl(planId: number, options?: { routeId?: number | null; mode?: "all" | "single" }): string {
  const params = new URLSearchParams();
  if (typeof options?.routeId === "number") params.set("route_id", String(options.routeId));
  params.set("mode", options?.mode ?? "all");
  return `${API_BASE}/api/v1/plans/${planId}/map.png?${params.toString()}`;
}

export async function generateMapPng(planId: number, options?: { routeId?: number | null; mode?: "all" | "single" }): Promise<JobAccepted> {
  const params: Record<string, string | number> = { mode: options?.mode ?? "all" };
  if (typeof options?.routeId === "number") params.route_id = options.routeId;
  const { data } = await api.post<JobAccepted>(`/api/v1/plans/${planId}/map.png`, null, { params });
  return data;
}

export async function startExportJob(
  planId: number,
  format: "csv" | "pdf",
  options?: { profile?: "planner" | "driver"; vehicleIdx?: number | null }
): Promise<JobAccepted> {
  const params: Record<string, string | number> = { format };
  if (options?.profile) params.profile = options.profile;
  if (typeof options?.vehicleIdx === "number") params.vehicle_idx = options.vehicleIdx;
  const { data } = await api.post<JobAccepted>(`/api/v1/plans/${planId}/export`, null, { params });
  return data;
}

export async function getJob(jobId: string): Promise<JobStatus> {
  const { data } = await api.get<JobStatus>(`/api/v1/jobs/${jobId}`);
  return data;
}

export function openJobEventStream(jobId: string): EventSource {
  return new EventSource(`${API_BASE}/api/v1/jobs/${jobId}/events`);
}

export function getJobFileUrl(jobId: string): string {
  return `${API_BASE}/api/v1/jobs/${jobId}/file`;
}

export async function getMlModels() {
  const { data } = await api.get("/api/v1/ml/models");
  return data;
}

export async function startMlTrain(datasetPath?: string | null): Promise<JobAccepted> {
  const { data } = await api.post<JobAccepted>("/api/v1/ml/models/train", { dataset_path: datasetPath ?? null });
  return data;
}

export async function setMlRollout(payload: {
  active_version: string;
  canary_version?: string | null;
  canary_percent?: number;
  enabled?: boolean;
}) {
  const { data } = await api.post("/api/v1/ml/rollout", payload);
  return data;
}

export async function uploadMlActuals(file: File) {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post("/api/v1/ml/actuals/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function getMlMetricsLatest() {
  const { data } = await api.get("/api/v1/ml/metrics/latest");
  return data;
}
