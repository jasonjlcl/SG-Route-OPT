import { useCallback, useEffect, useMemo, useState } from "react";

import { getDataset, getPlan } from "../api";

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
  const [dataset, setDataset] = useState<any>(null);
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
    const dsStatus = String(dataset?.status || "");
    const geocoded = Number(dataset?.geocode_counts?.SUCCESS || 0) + Number(dataset?.geocode_counts?.MANUAL || 0);
    const failed = Number(dataset?.geocode_counts?.FAILED || 0);
    const stopCount = Number(dataset?.stop_count || 0);

    const uploadStatus: StepStatus = datasetId > 0 ? "complete" : "in_progress";
    const validateStatus: StepStatus =
      datasetId === 0
        ? "not_started"
        : dsStatus.includes("VALIDATION_FAILED")
          ? "attention"
          : "complete";
    const geocodeStatus: StepStatus =
      datasetId === 0
        ? "not_started"
        : geocoded === 0 && failed === 0
          ? "in_progress"
          : geocoded > 0 && failed === 0
            ? "complete"
            : "attention";
    const optimizeStatus: StepStatus =
      planId === 0 ? "not_started" : String(plan?.status || "").toUpperCase() === "INFEASIBLE" ? "attention" : "complete";
    const resultsStatus: StepStatus = planId > 0 && stopCount > 0 ? "complete" : "not_started";

    return [
      { key: "upload", label: "Upload", route: "/upload", status: uploadStatus },
      { key: "validate", label: "Validate", route: "/validate", status: validateStatus },
      { key: "geocode", label: "Geocode", route: "/geocoding", status: geocodeStatus },
      { key: "optimize", label: "Optimize", route: "/optimization", status: optimizeStatus },
      { key: "results", label: "Results", route: "/results", status: resultsStatus },
    ];
  }, [dataset, datasetId, plan, planId]);

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
