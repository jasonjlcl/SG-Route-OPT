import { Clock3, Settings2, Sparkles, Wand2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { optimizeDataset } from "../api";
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
};

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

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OptimizationResult | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(() => localStorage.getItem("optimize_job_id"));
  const { job, start: startJobTracking } = useJobStatus();

  const loadFromJobResult = async (jobData: any) => {
    const resultRef = jobData?.result_ref as OptimizationResult | undefined;
    if (!resultRef) return;
    setResult(resultRef);
    if (resultRef.plan_id) {
      setPlanId(resultRef.plan_id);
      await refresh();
    }
  };

  useEffect(() => {
    if (activeJobId) {
      void startJobTracking(activeJobId);
    }
  }, [activeJobId, startJobTracking]);

  useEffect(() => {
    if (!job) return;
    if (job.status === "SUCCEEDED") {
      localStorage.removeItem("optimize_job_id");
      setActiveJobId(null);
      void loadFromJobResult(job);
      toast.success("Optimization complete", { description: "Plan is ready in Results." });
    } else if (job.status === "FAILED") {
      localStorage.removeItem("optimize_job_id");
      setActiveJobId(null);
      setError(job.message ?? "Optimization failed.");
      toast.error("Optimization failed", { description: job.message ?? "Adjust constraints and retry." });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status, job?.message]);

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
      setError("No dataset selected. Upload and geocode your stops first.");
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const payload = {
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
      };

      const accepted = await optimizeDataset(datasetId, payload);
      setActiveJobId(accepted.job_id);
      localStorage.setItem("optimize_job_id", accepted.job_id);
      await startJobTracking(accepted.job_id);
      toast.info("Optimization started", {
        description: "Running in background. You can monitor progress and come back later.",
      });
    } catch (err: any) {
      const msg = err?.response?.data?.message ?? "Optimization failed. Confirm geocoding and constraints.";
      setError(msg);
      toast.error("Optimization failed", {
        description: "Adjust constraints and retry.",
      });
    } finally {
      setLoading(false);
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
          {activeJobId && job && (
            <div className="rounded-lg border bg-muted/30 p-3 text-sm">
              <p className="font-semibold">Optimization progress: {job.progress}%</p>
              <p className="text-muted-foreground">{job.message ?? "Running..."}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {error && (
        <ErrorState
          title="Optimization failed"
          cause={error}
          nextStep="Check constraints and geocoding status, then rerun optimization."
          actionLabel="Dismiss"
          onAction={() => setError(null)}
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
                    <Button
                      key={suggestion}
                      variant="secondary"
                      size="sm"
                      onClick={() => applySuggestion(suggestion)}
                    >
                      <Wand2 className="mr-2 h-3.5 w-3.5" /> {suggestion}
                    </Button>
                  ))}
                </div>

                <p className="text-xs text-muted-foreground">
                  Tap a suggestion to auto-adjust fields, then run optimization again.
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

