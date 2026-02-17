import { useEffect, useMemo, useState } from "react";

import { getEvaluationPrediction, getHealth, getJobFileUrl, startEvaluationRun } from "../api";
import { useWorkflowContext } from "../components/layout/WorkflowContext";
import { EmptyState } from "../components/status/EmptyState";
import { ErrorState } from "../components/status/ErrorState";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { useJobStatus } from "../hooks/useJobStatus";
import type { EvaluationPredictionMetrics, EvaluationRunResult } from "../types";

export function EvaluationPage() {
  const { datasetId } = useWorkflowContext();
  const [featureEnabled, setFeatureEnabled] = useState(false);
  const [checkedFeature, setCheckedFeature] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [prediction, setPrediction] = useState<EvaluationPredictionMetrics | null>(null);
  const [report, setReport] = useState<EvaluationRunResult | null>(null);

  const [datasetInput, setDatasetInput] = useState<string>(datasetId > 0 ? String(datasetId) : "");
  const [depotLat, setDepotLat] = useState("1.3521");
  const [depotLon, setDepotLon] = useState("103.8198");
  const [numVehicles, setNumVehicles] = useState("2");
  const [capacity, setCapacity] = useState("20");
  const [workStart, setWorkStart] = useState("08:00");
  const [workEnd, setWorkEnd] = useState("18:00");
  const [solverLimit, setSolverLimit] = useState("20");
  const [sampleLimit, setSampleLimit] = useState("5000");

  const [jobId, setJobId] = useState<string | null>(null);
  const evalJob = useJobStatus();

  useEffect(() => {
    if (datasetId > 0) {
      setDatasetInput(String(datasetId));
    }
  }, [datasetId]);

  useEffect(() => {
    const load = async () => {
      try {
        const health = await getHealth();
        const enabled = Boolean(health.feature_eval_dashboard);
        setFeatureEnabled(enabled);
        if (enabled) {
          const pred = await getEvaluationPrediction(Number(sampleLimit) || 5000);
          setPrediction(pred);
        }
      } catch (err: any) {
        setError(err?.response?.data?.message ?? "Failed to load evaluation status.");
      } finally {
        setCheckedFeature(true);
      }
    };
    void load();
  }, []);

  useEffect(() => {
    if (!jobId) return;
    void evalJob.start(jobId);
  }, [jobId, evalJob.start]);

  useEffect(() => {
    if (!evalJob.job) return;
    if (evalJob.job.status === "SUCCEEDED") {
      const resultRef = (evalJob.job.result_ref || {}) as EvaluationRunResult;
      setReport(resultRef);
      setJobId(null);
    } else if (evalJob.job.status === "FAILED") {
      setError(evalJob.job.message ?? "Evaluation failed.");
      setJobId(null);
    }
  }, [evalJob.job]);

  const predictionCards = useMemo(() => {
    if (!prediction?.metrics) return null;
    return {
      mae: prediction.metrics.mae_improvement_pct,
      mape: prediction.metrics.mape_improvement_pct,
      sampleCount: prediction.samples,
      modelVersion: prediction.model_version || "not_trained",
    };
  }, [prediction]);

  const runEvaluation = async () => {
    try {
      setError(null);
      const id = Number(datasetInput);
      if (!Number.isFinite(id) || id <= 0) {
        setError("Provide a valid dataset ID.");
        return;
      }
      const accepted = await startEvaluationRun({
        dataset_id: id,
        depot_lat: Number(depotLat),
        depot_lon: Number(depotLon),
        fleet_config: {
          num_vehicles: Number(numVehicles),
          capacity: Number(capacity) > 0 ? Number(capacity) : null,
        },
        workday_start: workStart,
        workday_end: workEnd,
        solver: {
          solver_time_limit_s: Number(solverLimit),
          allow_drop_visits: true,
        },
        sample_limit: Number(sampleLimit),
      });
      setJobId(accepted.job_id);
      await evalJob.start(accepted.job_id);
    } catch (err: any) {
      setError(err?.response?.data?.message ?? "Unable to start evaluation.");
    }
  };

  if (!checkedFeature) {
    return <div className="text-sm text-muted-foreground">Loading evaluation dashboard...</div>;
  }

  if (!featureEnabled) {
    return (
      <EmptyState
        title="Evaluation dashboard disabled"
        description="Enable FEATURE_EVAL_DASHBOARD=true on the backend to use ML proof-of-improvement view."
      />
    );
  }

  return (
    <div className="space-y-4">
      {error && (
        <ErrorState
          title="Evaluation unavailable"
          cause={error}
          nextStep="Check feature flags, dataset readiness, then rerun evaluation."
          onAction={() => setError(null)}
          actionLabel="Dismiss"
        />
      )}

      <Card>
        <CardHeader>
          <CardTitle>Proof of Improvement</CardTitle>
          <CardDescription>Run baseline vs ML uplift evaluation with Google traffic as reference execution signal.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-4">
          <div className="space-y-2">
            <label className="text-sm">Dataset ID</label>
            <Input value={datasetInput} onChange={(event) => setDatasetInput(event.target.value)} />
          </div>
          <div className="space-y-2">
            <label className="text-sm">Depot lat</label>
            <Input value={depotLat} onChange={(event) => setDepotLat(event.target.value)} />
          </div>
          <div className="space-y-2">
            <label className="text-sm">Depot lon</label>
            <Input value={depotLon} onChange={(event) => setDepotLon(event.target.value)} />
          </div>
          <div className="space-y-2">
            <label className="text-sm">Vehicles</label>
            <Input value={numVehicles} onChange={(event) => setNumVehicles(event.target.value)} />
          </div>
          <div className="space-y-2">
            <label className="text-sm">Capacity</label>
            <Input value={capacity} onChange={(event) => setCapacity(event.target.value)} />
          </div>
          <div className="space-y-2">
            <label className="text-sm">Workday start</label>
            <Input type="time" value={workStart} onChange={(event) => setWorkStart(event.target.value)} />
          </div>
          <div className="space-y-2">
            <label className="text-sm">Workday end</label>
            <Input type="time" value={workEnd} onChange={(event) => setWorkEnd(event.target.value)} />
          </div>
          <div className="space-y-2">
            <label className="text-sm">Solver seconds</label>
            <Input value={solverLimit} onChange={(event) => setSolverLimit(event.target.value)} />
          </div>
          <div className="space-y-2 md:col-span-2">
            <label className="text-sm">Prediction sample limit</label>
            <Input value={sampleLimit} onChange={(event) => setSampleLimit(event.target.value)} />
          </div>
          <div className="flex items-end gap-2 md:col-span-2">
            <Button onClick={() => void runEvaluation()} disabled={Boolean(jobId)}>
              Run Evaluation
            </Button>
            {jobId && evalJob.job ? (
              <Badge variant="outline">
                {evalJob.job.status} {evalJob.job.progress}%
              </Badge>
            ) : null}
            {evalJob.job?.status === "SUCCEEDED" ? (
              <Button variant="outline" onClick={() => window.open(getJobFileUrl(evalJob.job!.job_id), "_blank")}>
                Download Report ZIP
              </Button>
            ) : null}
          </div>
        </CardContent>
      </Card>

      {predictionCards && (
        <div className="grid gap-3 sm:grid-cols-4">
          <Card>
            <CardContent className="p-4">
              <p className="text-xs uppercase text-muted-foreground">Prediction samples</p>
              <p className="text-xl font-semibold">{predictionCards.sampleCount}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <p className="text-xs uppercase text-muted-foreground">MAE improvement</p>
              <p className="text-xl font-semibold">{predictionCards.mae !== null && predictionCards.mae !== undefined ? `${predictionCards.mae.toFixed(2)}%` : "--"}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <p className="text-xs uppercase text-muted-foreground">MAPE improvement</p>
              <p className="text-xl font-semibold">
                {predictionCards.mape !== null && predictionCards.mape !== undefined ? `${predictionCards.mape.toFixed(2)}%` : "--"}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <p className="text-xs uppercase text-muted-foreground">Uplift model version</p>
              <p className="text-sm font-semibold">{predictionCards.modelVersion}</p>
            </CardContent>
          </Card>
        </div>
      )}

      {report?.planning?.comparison?.length ? (
        <Card>
          <CardHeader>
            <CardTitle>Planning KPI Delta (ML vs Baseline)</CardTitle>
            <CardDescription>{report.planning.summary || report.summary}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {report.planning.comparison.map((row) => (
              <div key={row.key} className="flex flex-wrap items-center justify-between gap-2 border-b pb-2 last:border-b-0">
                <span>{row.label}</span>
                <span className="text-muted-foreground">Baseline {row.baseline.toFixed(2)}</span>
                <span className="text-muted-foreground">ML {row.ml.toFixed(2)}</span>
                <span className="font-semibold">{row.improvement_pct !== null ? `${row.improvement_pct.toFixed(2)}%` : "--"}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
