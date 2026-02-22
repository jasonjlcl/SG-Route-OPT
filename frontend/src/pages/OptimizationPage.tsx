import { CircleHelp, Clock3, FlaskConical, Settings2, Sparkles, Wand2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { getHealth, getJobFileUrl, optimizeDataset, startOptimizeAbTest } from "../api";
import { useWorkflowContext } from "../components/layout/WorkflowContext";
import { useJobStatus } from "../hooks/useJobStatus";
import { EmptyState } from "../components/status/EmptyState";
import { ErrorState } from "../components/status/ErrorState";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../components/ui/tooltip";

type OptimizationResult = {
  plan_id: number;
  feasible: boolean;
  status?: string;
  objective_value?: number;
  total_makespan_s?: number;
  sum_vehicle_durations_s?: number;
  route_summary?: { vehicle_idx: number; stop_count: number; total_distance_m: number; total_duration_s: number }[];
  infeasibility_reason?: string;
  suggestions?: string[];
  eta_source?: "google_traffic" | "ml_uplift" | "ml_baseline" | "onemap" | null;
  traffic_timestamp?: string | null;
  live_traffic_requested?: boolean;
  warnings?: string[];
};

type AbSimulationResult = {
  comparison?: { key: string; label: string; baseline: number; ml: number; improvement_pct: number | null }[];
  baseline?: Record<string, unknown>;
  ml?: Record<string, unknown>;
  model_version?: string;
};

type OptimizeUiErrorAction = "dismiss" | "upload";

type OptimizeUiError = {
  title: string;
  cause: string;
  nextStep: string;
  action: OptimizeUiErrorAction;
  actionLabel: string;
  toastTitle: string;
  toastDescription: string;
};

function _toNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function _parseErrorDetails(raw: unknown): Record<string, unknown> {
  if (raw && typeof raw === "object") {
    return raw as Record<string, unknown>;
  }
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") {
        return parsed as Record<string, unknown>;
      }
    } catch {
      return {};
    }
  }
  return {};
}

function _buildOptimizeUiError(
  payload: { error_code?: unknown; message?: unknown; details?: unknown },
  mode: "optimization" | "ab_simulation"
): OptimizeUiError {
  const errorCode = String(payload.error_code ?? "").trim().toUpperCase();
  const message =
    typeof payload.message === "string" && payload.message.trim()
      ? payload.message.trim()
      : mode === "ab_simulation"
        ? "A/B simulation failed."
        : "Optimization failed.";

  const details = _parseErrorDetails(payload.details);
  const stopCount = _toNumber(details.stop_count);
  const maxStops = _toNumber(details.max_stops);
  const estimatedMatrixElements = _toNumber(details.estimated_matrix_elements);
  const maxMatrixElements = _toNumber(details.max_matrix_elements);

  if (errorCode === "OPTIMIZE_MAX_STOPS_EXCEEDED") {
    const cause =
      stopCount !== null && maxStops !== null
        ? `Dataset has ${stopCount} stops, but the current limit is ${maxStops}.`
        : "This dataset exceeds the configured stop limit for optimization.";
    return {
      title: "Request exceeds stop limit",
      cause,
      nextStep:
        "Split your input into smaller datasets (for example by zone or priority tier), re-upload, then rerun optimization.",
      action: "upload",
      actionLabel: "Go to Upload",
      toastTitle: "Optimization request too large",
      toastDescription: cause,
    };
  }

  if (errorCode === "OPTIMIZE_MAX_MATRIX_ELEMENTS_EXCEEDED") {
    const cause =
      estimatedMatrixElements !== null && maxMatrixElements !== null
        ? `Estimated matrix size is ${estimatedMatrixElements.toLocaleString()} elements, above the limit of ${maxMatrixElements.toLocaleString()}.`
        : "This dataset exceeds the configured matrix-size limit for optimization.";
    return {
      title: "Request exceeds matrix limit",
      cause,
      nextStep:
        "Reduce stop count or split this dataset into smaller runs, then rerun optimization to keep matrix build time bounded.",
      action: "upload",
      actionLabel: "Go to Upload",
      toastTitle: "Optimization request too large",
      toastDescription: cause,
    };
  }

  return {
    title: mode === "ab_simulation" ? "A/B simulation failed" : "Optimization failed",
    cause: message,
    nextStep:
      mode === "ab_simulation"
        ? "Check constraints and model settings, then rerun the simulation."
        : "Check constraints and geocoding status, then rerun optimization.",
    action: "dismiss",
    actionLabel: "Dismiss",
    toastTitle: mode === "ab_simulation" ? "A/B simulation failed" : "Optimization failed",
    toastDescription: message,
  };
}

function normalizeOptimizationResult(jobData: any): OptimizationResult | null {
  const resultRef = jobData?.result_ref;
  if (!resultRef || typeof resultRef !== "object") return null;

  // Pipeline jobs store optimize output under result_ref.optimize; keep direct shape for legacy paths.
  const raw = typeof resultRef.optimize === "object" && resultRef.optimize ? resultRef.optimize : resultRef;
  const planIdRaw = (raw as any).plan_id ?? (resultRef as any).plan_id;
  const planId = typeof planIdRaw === "number" ? planIdRaw : Number(planIdRaw || 0);

  return {
    ...(raw as OptimizationResult),
    plan_id: planId,
    warnings: Array.isArray((raw as any).warnings)
      ? ((raw as any).warnings as string[])
      : Array.isArray((resultRef as any).warnings)
        ? ((resultRef as any).warnings as string[])
        : undefined,
  };
}

export function OptimizationPage() {
  const navigate = useNavigate();
  const { datasetId, dataset, setPlanId, refresh } = useWorkflowContext();

  const [depotName, setDepotName] = useState("SG Central Depot");
  const [depotLat, setDepotLat] = useState("1.3521");
  const [depotLon, setDepotLon] = useState("103.8198");
  const [numVehicles, setNumVehicles] = useState("2");
  const [useCapacity, setUseCapacity] = useState(true);
  const [capacity, setCapacity] = useState("20");
  const [workStart, setWorkStart] = useState("08:00");
  const [workEnd, setWorkEnd] = useState("18:00");
  const [solverTimeLimit, setSolverTimeLimit] = useState("20");
  const [allowDrop, setAllowDrop] = useState(true);
  const [featureGoogleTraffic, setFeatureGoogleTraffic] = useState(false);
  const [useLiveTraffic, setUseLiveTraffic] = useState(false);
  const [experimentModelVersion, setExperimentModelVersion] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<OptimizeUiError | null>(null);
  const [result, setResult] = useState<OptimizationResult | null>(null);
  const [abResult, setAbResult] = useState<AbSimulationResult | null>(null);

  const [activeJobId, setActiveJobId] = useState<string | null>(() => localStorage.getItem("optimize_job_id"));
  const [experimentJobId, setExperimentJobId] = useState<string | null>(null);
  const optimizeJob = useJobStatus();
  const experimentJob = useJobStatus();

  const buildPayload = () => ({
    depot_lat: Number(depotLat),
    depot_lon: Number(depotLon),
    fleet: {
      num_vehicles: Number(numVehicles),
      capacity: useCapacity ? Number(capacity) : null,
    },
    workday_start: workStart,
    workday_end: workEnd,
    solver: {
      solver_time_limit_s: Number(solverTimeLimit),
      allow_drop_visits: allowDrop,
    },
    use_live_traffic: featureGoogleTraffic && useLiveTraffic,
  });

  const loadFromJobResult = async (jobData: any) => {
    const normalized = normalizeOptimizationResult(jobData);
    if (!normalized) return;
    setResult(normalized);
    if (normalized.plan_id) {
      setPlanId(normalized.plan_id);
      await refresh();
    }
  };

  useEffect(() => {
    const loadHealth = async () => {
      try {
        const health = await getHealth();
        setFeatureGoogleTraffic(Boolean(health.feature_google_traffic));
      } catch {
        setFeatureGoogleTraffic(false);
      }
    };
    void loadHealth();
  }, []);

  useEffect(() => {
    if (activeJobId) {
      void optimizeJob.start(activeJobId);
    }
  }, [activeJobId, optimizeJob.start]);

  useEffect(() => {
    if (experimentJobId) {
      void experimentJob.start(experimentJobId);
    }
  }, [experimentJobId, experimentJob.start]);

  useEffect(() => {
    const job = optimizeJob.job;
    if (!job) return;
    if (job.status === "SUCCEEDED") {
      setError(null);
      localStorage.removeItem("optimize_job_id");
      setActiveJobId(null);
      void loadFromJobResult(job);
      const warnings = normalizeOptimizationResult(job)?.warnings ?? [];
      if (warnings.length > 0) {
        toast.warning("Baseline ETA fallback", { description: warnings[0] });
      }
      toast.success("Optimization complete", { description: "Plan is ready in Results." });
    } else if (job.status === "FAILED") {
      localStorage.removeItem("optimize_job_id");
      setActiveJobId(null);
      const uiError = _buildOptimizeUiError(
        {
          error_code: job.error_code,
          message: job.message,
          details: job.error_detail,
        },
        "optimization"
      );
      setError(uiError);
      toast.error(uiError.toastTitle, { description: uiError.toastDescription });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [optimizeJob.job?.status, optimizeJob.job?.message]);

  useEffect(() => {
    const job = experimentJob.job;
    if (!job) return;
    if (job.status === "SUCCEEDED") {
      setError(null);
      setExperimentJobId(null);
      const resultRef = (job.result_ref || {}) as AbSimulationResult;
      setAbResult(resultRef);
      toast.success("A/B simulation complete", { description: "Baseline vs ML KPI comparison ready." });
    } else if (job.status === "FAILED") {
      setExperimentJobId(null);
      const uiError = _buildOptimizeUiError(
        {
          error_code: job.error_code,
          message: job.message,
          details: job.error_detail,
        },
        "ab_simulation"
      );
      setError(uiError);
      toast.error(uiError.toastTitle, { description: uiError.toastDescription });
    }
  }, [experimentJob.job]);

  const applySuggestion = (suggestion: string) => {
    const s = suggestion.toLowerCase();
    if (s.includes("add vehicles")) {
      setNumVehicles((current) => String(Number(current || "0") + 1));
    }
    if (s.includes("capacity")) {
      setUseCapacity(true);
      setCapacity((current) => String(Number(current || "0") + 5));
    }
    if (s.includes("relax time windows") || s.includes("extend workday")) {
      setWorkStart("07:00");
      setWorkEnd("20:00");
    }
    if (s.includes("reduce stops")) {
      toast.info("Stop reduction is not automated yet", {
        description: "Filter or edit your input file to remove low-priority stops, then rerun.",
      });
    }
  };

  const runOptimization = async () => {
    if (!datasetId) {
      setError({
        title: "No dataset selected",
        cause: "Upload and geocode a dataset before optimization.",
        nextStep: "Go to Upload, add a dataset, run geocoding, then return to Optimization.",
        action: "upload",
        actionLabel: "Go to Upload",
        toastTitle: "No dataset selected",
        toastDescription: "Upload and geocode a dataset before optimization.",
      });
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const accepted = await optimizeDataset(datasetId, buildPayload());
      setActiveJobId(accepted.job_id);
      localStorage.setItem("optimize_job_id", accepted.job_id);
      await optimizeJob.start(accepted.job_id);
      toast.info("Optimization started", {
        description: "Running in background. You can monitor progress and come back later.",
      });
    } catch (err: any) {
      const uiError = _buildOptimizeUiError(err?.response?.data ?? {}, "optimization");
      setError(uiError);
      toast.error(uiError.toastTitle, { description: uiError.toastDescription });
    } finally {
      setLoading(false);
    }
  };

  const runAbSimulation = async () => {
    if (!datasetId) return;
    try {
      setError(null);
      const payload = {
        ...buildPayload(),
        model_version: experimentModelVersion || null,
      };
      const accepted = await startOptimizeAbTest(datasetId, payload);
      setExperimentJobId(accepted.job_id);
      await experimentJob.start(accepted.job_id);
      toast.info("A/B simulation started", {
        description: "Comparing baseline fallback vs ML-enhanced optimization.",
      });
    } catch (err: any) {
      const uiError = _buildOptimizeUiError(err?.response?.data ?? {}, "ab_simulation");
      setError(uiError);
      toast.error(uiError.toastTitle, { description: uiError.toastDescription });
    }
  };

  const finishEstimate = useMemo(() => {
    if (!result?.route_summary?.length) return "--";
    const durationBase = Number(result.total_makespan_s || 0);
    const maxDuration = durationBase > 0 ? durationBase : Math.max(...result.route_summary.map((route) => route.total_duration_s));
    const [hour, minute] = workStart.split(":").map(Number);
    const totalMinutes = hour * 60 + minute + Math.round(maxDuration / 60);
    const finishHour = Math.floor(totalMinutes / 60) % 24;
    const finishMin = totalMinutes % 60;
    return `${String(finishHour).padStart(2, "0")}:${String(finishMin).padStart(2, "0")}`;
  }, [result, workStart]);

  if (!datasetId) {
    return (
      <EmptyState
        title="No dataset selected"
        description="Upload and geocode a dataset before optimization."
        actionLabel="Go to Upload"
        onAction={() => navigate("/upload")}
      />
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">Optimization setup</CardTitle>
          <CardDescription>Configure fleet constraints and solver settings for ML-enhanced VRPTW planning.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-4 rounded-xl border p-4">
              <h3 className="text-sm font-semibold uppercase text-muted-foreground">Depot & fleet</h3>
              <div className="space-y-2">
                <Label>Depot name</Label>
                <Input value={depotName} onChange={(event) => setDepotName(event.target.value)} placeholder="Central Hub" />
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label>Depot latitude</Label>
                  <Input value={depotLat} onChange={(event) => setDepotLat(event.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label>Depot longitude</Label>
                  <Input value={depotLon} onChange={(event) => setDepotLon(event.target.value)} />
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label>Number of vehicles</Label>
                  <Input value={numVehicles} onChange={(event) => setNumVehicles(event.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label className="flex items-center justify-between">
                    Capacity limit
                    <input type="checkbox" checked={useCapacity} onChange={(event) => setUseCapacity(event.target.checked)} />
                  </Label>
                  <Input value={capacity} disabled={!useCapacity} onChange={(event) => setCapacity(event.target.value)} />
                </div>
              </div>
            </div>

            <div className="space-y-4 rounded-xl border p-4">
              <h3 className="text-sm font-semibold uppercase text-muted-foreground">Workday & solver</h3>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label>Workday start</Label>
                  <Input type="time" value={workStart} onChange={(event) => setWorkStart(event.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label>Workday end</Label>
                  <Input type="time" value={workEnd} onChange={(event) => setWorkEnd(event.target.value)} />
                </div>
              </div>

              <div className="space-y-2">
                <Label>Solver time limit (seconds)</Label>
                <Input value={solverTimeLimit} onChange={(event) => setSolverTimeLimit(event.target.value)} />
              </div>

              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={allowDrop} onChange={(event) => setAllowDrop(event.target.checked)} />
                Allow dropped stops with penalty when full feasibility is impossible
              </label>

              {featureGoogleTraffic && (
                <div className="flex items-center justify-between rounded-lg border bg-muted/20 px-3 py-2 text-sm">
                  <div className="flex items-center gap-2">
                    <span>Use live traffic (Google)</span>
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <button type="button" className="text-muted-foreground">
                            <CircleHelp className="h-4 w-4" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent>
                          Uses Google traffic-aware travel times. Falls back automatically if unavailable.
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                  <input type="checkbox" checked={useLiveTraffic} onChange={(event) => setUseLiveTraffic(event.target.checked)} />
                </div>
              )}

              <div className="rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
                <p className="mb-1 flex items-center gap-1 font-semibold text-foreground">
                  <Settings2 className="h-3.5 w-3.5" /> What this affects
                </p>
                <p>Vehicle count and capacity drive feasibility, while workday and solver settings influence route quality and runtime.</p>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button size="lg" onClick={() => void runOptimization()} disabled={loading || !!activeJobId}>
              {loading ? (
                <>
                  <Clock3 className="mr-2 h-4 w-4 animate-spin" /> Optimizing routes...
                </>
              ) : (
                <>
                  <Sparkles className="mr-2 h-4 w-4" /> Run optimization
                </>
              )}
            </Button>
            <Button
              size="lg"
              variant="outline"
              onClick={() => navigate("/results")}
              disabled={dataset?.optimize_state !== "COMPLETE" && !(result?.feasible && result?.plan_id)}
            >
              Open results
            </Button>
          </div>
          {activeJobId && optimizeJob.job && (
            <div className="rounded-lg border bg-muted/30 p-3 text-sm">
              <p className="font-semibold">Optimization progress: {optimizeJob.job.progress}%</p>
              {optimizeJob.job.current_step ? <p className="text-xs text-muted-foreground">Step: {optimizeJob.job.current_step}</p> : null}
              <p className="text-muted-foreground">{optimizeJob.job.message ?? "Running..."}</p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>A/B Simulation Mode</CardTitle>
          <CardDescription>Compare baseline fallback vs ML-enhanced optimization on the same constraints and dataset.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 md:grid-cols-[1fr_auto]">
            <Input
              value={experimentModelVersion}
              onChange={(event) => setExperimentModelVersion(event.target.value)}
              placeholder="Optional model version override (otherwise active rollout)"
            />
            <Button variant="outline" onClick={() => void runAbSimulation()} disabled={!!experimentJobId}>
              <FlaskConical className="mr-2 h-4 w-4" /> Run A/B simulation
            </Button>
          </div>
          {experimentJob.job && (
            <div className="rounded-lg border p-3 text-sm">
              <p className="font-semibold">Experiment progress: {experimentJob.job.progress}%</p>
              <p className="text-muted-foreground">{experimentJob.job.message}</p>
            </div>
          )}
          {abResult?.comparison?.length ? (
            <div className="space-y-2 rounded-lg border p-3 text-sm">
              <p className="font-semibold">Baseline vs ML KPI impact</p>
              {abResult.comparison.map((row) => (
                <div key={row.key} className="flex flex-wrap items-center justify-between gap-2 border-b pb-2 last:border-b-0">
                  <span>{row.label}</span>
                  <span className="text-muted-foreground">Baseline {row.baseline.toFixed(2)}</span>
                  <span className="text-muted-foreground">ML {row.ml.toFixed(2)}</span>
                  <span className="font-semibold">{row.improvement_pct !== null ? `${row.improvement_pct.toFixed(2)}%` : "--"}</span>
                </div>
              ))}
              {experimentJob.job?.job_id ? (
                <div className="pt-2">
                  <Button variant="secondary" onClick={() => window.open(getJobFileUrl(experimentJob.job!.job_id), "_blank")}>
                    Download A/B report package
                  </Button>
                </div>
              ) : null}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {error && (
        <ErrorState
          title={error.title}
          cause={error.cause}
          nextStep={error.nextStep}
          actionLabel={error.actionLabel}
          onAction={error.action === "upload" ? () => navigate("/upload") : () => setError(null)}
        />
      )}

      {result && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Run summary
              {result.feasible ? <Badge variant="success">Feasible</Badge> : <Badge variant="danger">Infeasible</Badge>}
            </CardTitle>
            <CardDescription>Route run #{result.plan_id} • Depot: {depotName} • Estimated finish: {finishEstimate}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {result.feasible ? (
              <>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div className="rounded-xl border p-3">
                    <p className="text-xs uppercase text-muted-foreground">Plan status</p>
                    <p className="text-xl font-semibold">{result.status}</p>
                  </div>
                  <div className="rounded-xl border p-3">
                    <p className="text-xs uppercase text-muted-foreground">Objective value</p>
                    <p className="text-xl font-semibold">{Math.round(result.objective_value || 0)}</p>
                  </div>
                  <div className="rounded-xl border p-3">
                    <p className="text-xs uppercase text-muted-foreground">Vehicles used</p>
                    <p className="text-xl font-semibold">{result.route_summary?.length || 0}</p>
                  </div>
                </div>

                <div className="rounded-xl border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Vehicle</TableHead>
                        <TableHead>Stops</TableHead>
                        <TableHead>Distance</TableHead>
                        <TableHead>Duration</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {result.route_summary?.map((route) => (
                        <TableRow key={route.vehicle_idx}>
                          <TableCell>Vehicle {route.vehicle_idx}</TableCell>
                          <TableCell>{route.stop_count}</TableCell>
                          <TableCell>{(route.total_distance_m / 1000).toFixed(1)} km</TableCell>
                          <TableCell>{Math.round(route.total_duration_s / 60)} min</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </>
            ) : (
              <div className="space-y-4 rounded-xl border border-danger/40 bg-danger/5 p-4">
                <div>
                  <p className="text-sm font-semibold text-danger">Why optimization failed</p>
                  <p className="text-sm text-muted-foreground">
                    Category: <span className="font-medium capitalize">{result.infeasibility_reason || "constraint conflict"}</span>
                  </p>
                </div>

                <div className="flex flex-wrap gap-2">
                  {result.suggestions?.map((suggestion) => (
                    <Button key={suggestion} variant="secondary" size="sm" onClick={() => applySuggestion(suggestion)}>
                      <Wand2 className="mr-2 h-3.5 w-3.5" /> {suggestion}
                    </Button>
                  ))}
                </div>

                <p className="text-xs text-muted-foreground">Tap a suggestion to auto-adjust fields, then run optimization again.</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
