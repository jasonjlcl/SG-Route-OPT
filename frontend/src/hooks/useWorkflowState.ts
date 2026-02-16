import { useCallback, useEffect, useMemo, useState } from "react";

import { getDataset, getPlan } from "../api";
import type { DatasetSummary } from "../types";

export type StepStatus = "not_started" | "in_progress" | "complete" | "attention";

export type WorkflowStep = {
  key: "upload" | "validate" | "geocode" | "optimize" | "results";
  label: string;
  route: string;
  status: StepStatus;
};

export function useWorkflowState() {
  const [datasetId, setDatasetIdState] = useState<number>(() => Number(localStorage.getItem("dataset_id") || "0"));
  const [planId, setPlanIdState] = useState<number>(() => Number(localStorage.getItem("plan_id") || "0"));
  const [dataset, setDataset] = useState<DatasetSummary | null>(null);
  const [plan, setPlan] = useState<any>(null);

  const setDatasetId = useCallback((id: number) => {
    setDatasetIdState(id);
    localStorage.setItem("dataset_id", String(id));
  }, []);

  const setPlanId = useCallback((id: number) => {
    setPlanIdState(id);
    localStorage.setItem("plan_id", String(id));
  }, []);

  const refresh = useCallback(async () => {
    if (datasetId > 0) {
      try {
        const ds = await getDataset(datasetId);
        setDataset(ds);
      } catch {
        setDataset(null);
      }
    } else {
      setDataset(null);
    }

    if (planId > 0) {
      try {
        const p = await getPlan(planId);
        setPlan(p);
      } catch {
        setPlan(null);
      }
    } else {
      setPlan(null);
    }
  }, [datasetId, planId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const steps: WorkflowStep[] = useMemo(() => {
    const uploadStatus: StepStatus = datasetId > 0 ? "complete" : "not_started";

    const validationState = dataset?.validation_state ?? "NOT_STARTED";
    const geocodeState = dataset?.geocode_state ?? "NOT_STARTED";
    const optimizeState = dataset?.optimize_state ?? "NOT_STARTED";

    const validateStatus: StepStatus =
      validationState === "VALID" || validationState === "PARTIAL"
        ? "complete"
        : validationState === "BLOCKED"
          ? "attention"
          : datasetId > 0
            ? "in_progress"
            : "not_started";

    const geocodeStatus: StepStatus =
      geocodeState === "COMPLETE"
        ? "complete"
        : geocodeState === "NEEDS_ATTENTION"
          ? "attention"
          : geocodeState === "IN_PROGRESS"
            ? "in_progress"
            : datasetId > 0
              ? "in_progress"
              : "not_started";

    const optimizeStatus: StepStatus =
      optimizeState === "COMPLETE"
        ? "complete"
        : optimizeState === "NEEDS_ATTENTION"
          ? "attention"
          : optimizeState === "RUNNING"
            ? "in_progress"
            : geocodeState === "COMPLETE"
              ? "in_progress"
              : "not_started";

    const viewedPlanId = Number(localStorage.getItem("results_viewed_plan_id") || "0");
    const effectivePlanId = dataset?.latest_plan_id ?? planId;
    const hasView = effectivePlanId > 0 && viewedPlanId === effectivePlanId;
    const resultsStatus: StepStatus = effectivePlanId <= 0 ? "not_started" : hasView ? "complete" : "in_progress";

    return [
      { key: "upload", label: "Upload", route: "/upload", status: uploadStatus },
      { key: "validate", label: "Validate", route: "/validate", status: validateStatus },
      { key: "geocode", label: "Geocode", route: "/geocoding", status: geocodeStatus },
      { key: "optimize", label: "Optimize", route: "/optimization", status: optimizeStatus },
      { key: "results", label: "Results", route: "/results", status: resultsStatus },
    ];
  }, [dataset, datasetId, planId]);

  return {
    datasetId,
    planId,
    dataset,
    plan,
    setDatasetId,
    setPlanId,
    steps,
    refresh,
  };
}
