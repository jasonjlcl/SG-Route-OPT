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
  const [isRefreshing, setIsRefreshing] = useState(false);

  const setDatasetId = useCallback((id: number) => {
    setDatasetIdState(id);
    localStorage.setItem("dataset_id", String(id));
  }, []);

  const setPlanId = useCallback((id: number) => {
    setPlanIdState(id);
    localStorage.setItem("plan_id", String(id));
  }, []);

  const refresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      let effectivePlanId = planId;

      if (datasetId > 0) {
        try {
          const ds = await getDataset(datasetId);
          setDataset(ds);
          const latestPlanId = Number(ds.latest_plan_id || 0);
          if (latestPlanId > 0) {
            effectivePlanId = latestPlanId;
            if (latestPlanId !== planId) {
              setPlanIdState(latestPlanId);
              localStorage.setItem("plan_id", String(latestPlanId));
            }
          }
        } catch {
          setDataset(null);
        }
      } else {
        setDataset(null);
      }

      if (effectivePlanId > 0) {
        try {
          const p = await getPlan(effectivePlanId);
          setPlan(p);
        } catch {
          setPlan(null);
        }
      } else {
        setPlan(null);
      }
    } finally {
      setIsRefreshing(false);
    }
  }, [datasetId, planId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const steps: WorkflowStep[] = useMemo(() => {
    if (datasetId <= 0) {
      return [
        { key: "upload", label: "Upload", route: "/upload", status: "not_started" },
        { key: "validate", label: "Validate", route: "/validate", status: "not_started" },
        { key: "geocode", label: "Geocode", route: "/geocoding", status: "not_started" },
        { key: "optimize", label: "Optimize", route: "/optimization", status: "not_started" },
        { key: "results", label: "Results", route: "/results", status: "not_started" },
      ];
    }

    const uploadStatus: StepStatus = datasetId > 0 ? "complete" : "not_started";

    const validationState = dataset?.validation_state ?? "NOT_STARTED";
    const geocodeState = dataset?.geocode_state ?? "NOT_STARTED";
    const optimizeState = dataset?.optimize_state ?? "NOT_STARTED";
    const isGeocodingRunning = dataset?.status === "GEOCODING_RUNNING";
    const isOptimizeRunning = dataset?.status === "OPTIMIZATION_RUNNING" || optimizeState === "RUNNING";

    const validateStatus: StepStatus =
      validationState === "VALID"
        ? "complete"
        : validationState === "BLOCKED"
          ? "attention"
          : validationState === "PARTIAL"
            ? "attention"
          : "not_started";

    const geocodeStatus: StepStatus =
      geocodeState === "COMPLETE"
        ? "complete"
        : geocodeState === "NEEDS_ATTENTION"
          ? "attention"
          : geocodeState === "IN_PROGRESS"
            ? isGeocodingRunning
              ? "in_progress"
              : "not_started"
            : "not_started";

    const optimizeStatus: StepStatus =
      optimizeState === "COMPLETE"
        ? "complete"
        : optimizeState === "NEEDS_ATTENTION"
          ? "attention"
          : optimizeState === "RUNNING"
            ? isOptimizeRunning
              ? "in_progress"
              : "not_started"
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
    isRefreshing,
  };
}
