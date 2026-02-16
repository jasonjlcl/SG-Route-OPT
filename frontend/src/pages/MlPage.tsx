import { useEffect, useMemo, useState } from "react";

import {
  getJobFileUrl,
  getMlConfig,
  getMlEvaluationCompare,
  getMlMetricsLatest,
  getMlModels,
  runMlDriftReport,
  setMlConfig,
  startMlEvaluationReport,
  startMlTrain,
  uploadMlActuals,
} from "../api";
import { useJobStatus } from "../hooks/useJobStatus";
import type { MlEvaluationComparison } from "../types";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";

export function MlPage() {
  const [modelsPayload, setModelsPayload] = useState<any>({ models: [], rollout: null });
  const [metrics, setMetrics] = useState<any>(null);
  const [comparison, setComparison] = useState<MlEvaluationComparison | null>(null);

  const [activeVersion, setActiveVersion] = useState("");
  const [canaryVersion, setCanaryVersion] = useState("");
  const [canaryPercent, setCanaryPercent] = useState("0");
  const [canaryEnabled, setCanaryEnabled] = useState(false);
  const [actualsFile, setActualsFile] = useState<File | null>(null);

  const [daysWindow, setDaysWindow] = useState("30");
  const [sampleLimit, setSampleLimit] = useState("5000");
  const [compareModelVersion, setCompareModelVersion] = useState("");
  const [trainJobId, setTrainJobId] = useState<string | null>(null);
  const [evalJobId, setEvalJobId] = useState<string | null>(null);

  const trainJobState = useJobStatus();
  const evalJobState = useJobStatus();

  const load = async () => {
    const [models, latestMetrics, config] = await Promise.all([getMlModels(), getMlMetricsLatest(), getMlConfig()]);
    setModelsPayload(models);
    setMetrics(latestMetrics);
    setActiveVersion(config?.active_model_version || models?.rollout?.active_version || "");
    setCanaryVersion(config?.canary_model_version || models?.rollout?.canary_version || "");
    setCanaryPercent(String(config?.canary_percent ?? models?.rollout?.canary_percent ?? 0));
    setCanaryEnabled(Boolean(config?.canary_enabled ?? models?.rollout?.enabled ?? false));
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!trainJobId) return;
    void trainJobState.start(trainJobId);
  }, [trainJobId, trainJobState.start]);

  useEffect(() => {
    if (!evalJobId) return;
    void evalJobState.start(evalJobId);
  }, [evalJobId, evalJobState.start]);

  useEffect(() => {
    if (trainJobState.job?.status === "SUCCEEDED") {
      void load();
      setTrainJobId(null);
    }
  }, [trainJobState.job?.status]);

  useEffect(() => {
    if (!evalJobState.job) return;
    if (evalJobState.job.status === "SUCCEEDED") {
      setEvalJobId(null);
      window.open(getJobFileUrl(evalJobState.job.job_id), "_blank");
    }
  }, [evalJobState.job]);

  const evaluationSummary = useMemo(() => {
    if (!comparison) return null;
    const rows = comparison.kpis ?? [];
    const mae = rows.find((row) => row.key === "mae_s");
    const mape = rows.find((row) => row.key === "mape_pct");
    const rmse = rows.find((row) => row.key === "rmse_s");
    return { mae, mape, rmse };
  }, [comparison]);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>ML Settings</CardTitle>
          <CardDescription>Manage model versions, rollout, and monitoring metrics.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={async () => {
                const accepted = await startMlTrain(null);
                setTrainJobId(accepted.job_id);
              }}
            >
              Train from actuals
            </Button>
            <Button variant="outline" onClick={() => void load()}>
              Refresh
            </Button>
          </div>
          {trainJobState.job && (
            <div className="rounded-lg border p-3 text-sm">
              <p className="font-semibold">
                Job {trainJobState.job.type}: {trainJobState.job.progress}%
              </p>
              <p className="text-muted-foreground">{trainJobState.job.message}</p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Rollout</CardTitle>
          <CardDescription>Set active and canary model versions.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <div className="space-y-2">
            <label className="text-sm">Active version</label>
            <Input value={activeVersion} onChange={(event) => setActiveVersion(event.target.value)} placeholder="v20260101010101" />
          </div>
          <div className="space-y-2">
            <label className="text-sm">Canary version</label>
            <Input value={canaryVersion} onChange={(event) => setCanaryVersion(event.target.value)} placeholder="optional" />
          </div>
          <div className="space-y-2">
            <label className="text-sm">Canary percent</label>
            <Input value={canaryPercent} onChange={(event) => setCanaryPercent(event.target.value)} />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={canaryEnabled} onChange={(event) => setCanaryEnabled(event.target.checked)} />
            Enable canary
          </label>
          <div className="md:col-span-2">
            <Button
              onClick={async () => {
                await setMlConfig({
                  active_model_version: activeVersion,
                  canary_model_version: canaryVersion || null,
                  canary_percent: Number(canaryPercent),
                  canary_enabled: canaryEnabled,
                });
                await load();
              }}
            >
              Save rollout
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Upload actuals</CardTitle>
          <CardDescription>CSV columns: origin_lat, origin_lon, dest_lat, dest_lon, timestamp_iso, actual_duration_s.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          <Input type="file" accept=".csv" onChange={(event) => setActualsFile(event.target.files?.[0] || null)} className="max-w-md" />
          <Button
            disabled={!actualsFile}
            onClick={async () => {
              if (!actualsFile) return;
              await uploadMlActuals(actualsFile);
              await load();
            }}
          >
            Upload
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Formal Evaluation (Baseline vs ML)</CardTitle>
          <CardDescription>Compute 5 KPI comparisons and export report artifacts (CSV + plots) for project defense.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 md:grid-cols-3">
            <div className="space-y-2">
              <label className="text-sm">Window (days)</label>
              <Input value={daysWindow} onChange={(event) => setDaysWindow(event.target.value)} />
            </div>
            <div className="space-y-2">
              <label className="text-sm">Sample limit</label>
              <Input value={sampleLimit} onChange={(event) => setSampleLimit(event.target.value)} />
            </div>
            <div className="space-y-2">
              <label className="text-sm">Model version override</label>
              <Input value={compareModelVersion} onChange={(event) => setCompareModelVersion(event.target.value)} placeholder="optional" />
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={async () => {
                const data = await getMlEvaluationCompare({
                  days: Number(daysWindow),
                  limit: Number(sampleLimit),
                  modelVersion: compareModelVersion || null,
                });
                setComparison(data);
              }}
            >
              Run baseline vs ML comparison
            </Button>
            <Button
              variant="outline"
              onClick={async () => {
                const accepted = await startMlEvaluationReport({
                  days: Number(daysWindow),
                  limit: Number(sampleLimit),
                  modelVersion: compareModelVersion || null,
                });
                setEvalJobId(accepted.job_id);
              }}
            >
              Generate report package
            </Button>
          </div>
          {evalJobState.job && (
            <div className="rounded-lg border p-3 text-sm">
              <p className="font-semibold">
                Evaluation job: {evalJobState.job.progress}%
              </p>
              <p className="text-muted-foreground">{evalJobState.job.message}</p>
            </div>
          )}
          {evaluationSummary && (
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-lg border p-3 text-sm">
                <p className="text-muted-foreground">MAE improvement</p>
                <p className="text-lg font-semibold">{evaluationSummary.mae?.improvement_pct?.toFixed(2) ?? "--"}%</p>
              </div>
              <div className="rounded-lg border p-3 text-sm">
                <p className="text-muted-foreground">MAPE improvement</p>
                <p className="text-lg font-semibold">{evaluationSummary.mape?.improvement_pct?.toFixed(2) ?? "--"}%</p>
              </div>
              <div className="rounded-lg border p-3 text-sm">
                <p className="text-muted-foreground">RMSE improvement</p>
                <p className="text-lg font-semibold">{evaluationSummary.rmse?.improvement_pct?.toFixed(2) ?? "--"}%</p>
              </div>
            </div>
          )}
          {comparison?.kpis?.length ? (
            <div className="rounded-lg border p-3 text-sm">
              <p className="mb-2 font-semibold">KPI Table</p>
              <div className="space-y-2">
                {comparison.kpis.map((row) => (
                  <div key={row.key} className="flex flex-wrap items-center justify-between gap-2 border-b pb-2 last:border-b-0">
                    <span>{row.label}</span>
                    <span className="text-muted-foreground">Baseline {row.baseline.toFixed(2)}</span>
                    <span className="text-muted-foreground">Model {(row.model ?? row.ml ?? 0).toFixed(2)}</span>
                    <span className="font-semibold">{row.improvement_pct !== null ? `${row.improvement_pct.toFixed(2)}%` : "--"}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Latest metrics</CardTitle>
          <CardDescription>MAE/MAPE and drift score from recent prediction logs.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <Button
            variant="outline"
            size="sm"
            onClick={async () => {
              await runMlDriftReport(false);
              await load();
            }}
          >
            Run drift report now
          </Button>
          <p>MAE: {metrics?.mae ?? "--"}</p>
          <p>MAPE: {metrics?.mape ?? "--"}</p>
          <p>Drift score: {metrics?.drift_score ?? "--"}</p>
          <Badge variant={metrics?.needs_retrain ? "warning" : "success"}>{metrics?.needs_retrain ? "Needs retrain" : "Healthy"}</Badge>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Model registry</CardTitle>
          <CardDescription>Registered model versions and metrics.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {modelsPayload.models?.map((model: any) => (
            <div key={model.version} className="rounded-lg border p-3 text-sm">
              <p className="font-semibold">{model.version}</p>
              <p className="text-muted-foreground">Status: {model.status}</p>
              <p className="text-muted-foreground">
                MAE: {model.metrics_json?.mae ?? "--"} | MAPE: {model.metrics_json?.mape ?? "--"} | RMSE: {model.metrics_json?.rmse ?? "--"}
              </p>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
