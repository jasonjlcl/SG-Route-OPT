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
  geocode_status: string;
  geocode_meta: string | null;
};

export type PlanDetails = {
  plan_id: number;
  dataset_id: number;
  status: string;
  objective_value: number;
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
