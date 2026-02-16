import { useEffect, useState } from "react";

import { getMlMetricsLatest, getMlModels, setMlRollout, startMlTrain, uploadMlActuals } from "../api";
import { useJobStatus } from "../hooks/useJobStatus";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";

export function MlPage() {
  const [modelsPayload, setModelsPayload] = useState<any>({ models: [], rollout: null });
  const [metrics, setMetrics] = useState<any>(null);
  const [activeVersion, setActiveVersion] = useState("");
  const [canaryVersion, setCanaryVersion] = useState("");
  const [canaryPercent, setCanaryPercent] = useState("0");
  const [canaryEnabled, setCanaryEnabled] = useState(false);
  const [actualsFile, setActualsFile] = useState<File | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const { job, start } = useJobStatus();

  const load = async () => {
    const [models, latestMetrics] = await Promise.all([getMlModels(), getMlMetricsLatest()]);
    setModelsPayload(models);
    setMetrics(latestMetrics);
    const rollout = models.rollout;
    if (rollout) {
      setActiveVersion(rollout.active_version || "");
      setCanaryVersion(rollout.canary_version || "");
      setCanaryPercent(String(rollout.canary_percent || 0));
      setCanaryEnabled(Boolean(rollout.enabled));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!jobId) return;
    void start(jobId);
  }, [jobId, start]);

  useEffect(() => {
    if (job?.status === "SUCCEEDED") {
      void load();
      setJobId(null);
    }
  }, [job]);

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
                setJobId(accepted.job_id);
              }}
            >
              Train from actuals
            </Button>
            <Button variant="outline" onClick={() => void load()}>
              Refresh
            </Button>
          </div>
          {job && (
            <div className="rounded-lg border p-3 text-sm">
              <p className="font-semibold">
                Job {job.type}: {job.progress}%
              </p>
              <p className="text-muted-foreground">{job.message}</p>
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
                await setMlRollout({
                  active_version: activeVersion,
                  canary_version: canaryVersion || null,
                  canary_percent: Number(canaryPercent),
                  enabled: canaryEnabled,
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
          <CardTitle>Latest metrics</CardTitle>
          <CardDescription>MAE/MAPE and drift score from recent prediction logs.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>MAE: {metrics?.mae ?? "--"}</p>
          <p>MAPE: {metrics?.mape ?? "--"}</p>
          <p>Drift score: {metrics?.drift_score ?? "--"}</p>
          <Badge variant={metrics?.needs_retrain ? "warning" : "success"}>
            {metrics?.needs_retrain ? "Needs retrain" : "Healthy"}
          </Badge>
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
              <p className="text-muted-foreground">MAE: {model.metrics_json?.mae ?? "--"} | MAPE: {model.metrics_json?.mape ?? "--"}</p>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

