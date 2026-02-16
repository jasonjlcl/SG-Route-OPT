export type ValidationIssue = {
  row_index: number;
  reason: string;
};

export type UploadResponse = {
  dataset_id: number;
  validation_summary: {
    valid_rows_count: number;
    invalid_rows_count: number;
    invalid_rows: ValidationIssue[];
  };
  next_action: string;
};

export type StopItem = {
  id: number;
  stop_ref: string;
  address: string | null;
  postal_code: string | null;
  lat: number | null;
  lon: number | null;
  demand: number;
  service_time_min: number;
  tw_start: string | null;
  tw_end: string | null;
  phone: string | null;
  contact_name: string | null;
  geocode_status: string;
  geocode_meta: string | null;
};

export type DatasetSummary = {
  id: number;
  filename: string;
  created_at: string;
  status: string;
  stop_count: number;
  valid_stop_count: number;
  geocode_counts: Record<string, number>;
  validation_state: "NOT_STARTED" | "BLOCKED" | "PARTIAL" | "VALID";
  geocode_state: "NOT_STARTED" | "IN_PROGRESS" | "COMPLETE" | "NEEDS_ATTENTION";
  optimize_state: "NOT_STARTED" | "RUNNING" | "COMPLETE" | "NEEDS_ATTENTION";
  latest_plan_id: number | null;
  latest_plan_status: string | null;
};

export type PlanDetails = {
  plan_id: number;
  dataset_id: number;
  status: string;
  objective_value: number;
  total_makespan_s: number | null;
  sum_vehicle_durations_s: number;
  infeasibility_reason: string | null;
  depot: {
    lat: number;
    lon: number;
  };
  routes: {
    route_id: number;
    vehicle_idx: number;
    total_distance_m: number;
    total_duration_s: number;
    stops: {
      sequence_idx: number;
      stop_id: number | null;
      stop_ref: string;
      address: string;
      lat: number;
      lon: number;
      phone?: string | null;
      contact_name?: string | null;
      eta_iso: string;
      arrival_window_start_iso: string;
      arrival_window_end_iso: string;
      service_start_iso: string;
      service_end_iso: string;
    }[];
  }[];
  unserved_stops: {
    stop_id: number;
    stop_ref: string;
    address: string | null;
  }[];
};

export type JobAccepted = {
  job_id: string;
  status: string;
  type: string;
};

export type JobStatus = {
  job_id: string;
  type: string;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
  progress: number;
  message: string | null;
  result_ref: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};
