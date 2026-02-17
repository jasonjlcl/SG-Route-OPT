import L, { DivIcon } from "leaflet";
import { CheckCircle2, LocateFixed, RefreshCcw, Search, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { MapContainer, Marker, TileLayer, Tooltip, useMap } from "react-leaflet";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { getDataset, getStops, manualResolveStop, runGeocoding } from "../api";
import { useWorkflowContext } from "../components/layout/WorkflowContext";
import { useJobStatus } from "../hooks/useJobStatus";
import { EmptyState } from "../components/status/EmptyState";
import { ErrorState } from "../components/status/ErrorState";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Progress } from "../components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { checkCoordinate } from "../lib/geo";
import type { StopItem } from "../types";

const statusFilterToBackend: Record<string, string | undefined> = {
  all: undefined,
  geocoded: "SUCCESS",
  failed: "FAILED",
  manual: "MANUAL",
};

function markerLabel(index: number): DivIcon {
  return L.divIcon({
    className: "",
    html: `<div class='route-seq-marker'>${index + 1}</div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });
}

function FitMapToStops({ points }: { points: [number, number][] }) {
  const map = useMap();

  useEffect(() => {
    if (points.length === 0) return;
    if (points.length === 1) {
      map.setView(points[0], 13, { animate: false });
      return;
    }
    map.fitBounds(L.latLngBounds(points), { padding: [24, 24], animate: false });
  }, [map, points]);

  return null;
}

export function GeocodingPage() {
  const navigate = useNavigate();
  const { datasetId, setDatasetId, refresh: refreshWorkflow } = useWorkflowContext();

  const [datasetInfo, setDatasetInfo] = useState<any>(null);
  const [stops, setStops] = useState<StopItem[]>([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedStop, setSelectedStop] = useState<StopItem | null>(null);
  const [resolveTab, setResolveTab] = useState("search");
  const [addressInput, setAddressInput] = useState("");
  const [postalInput, setPostalInput] = useState("");
  const [latInput, setLatInput] = useState("");
  const [lonInput, setLonInput] = useState("");
  const [activeJobId, setActiveJobId] = useState<string | null>(() => localStorage.getItem("geocode_job_id"));
  const { job, jobError, start: startJobTracking } = useJobStatus();

  const loadData = async () => {
    if (!datasetId) return;
    try {
      const [dataset, stopResp] = await Promise.all([
        getDataset(datasetId),
        getStops(datasetId, statusFilterToBackend[statusFilter]),
      ]);
      setDatasetInfo(dataset);
      setStops(stopResp.items);
      await refreshWorkflow();
    } catch (err: any) {
      setError(err?.response?.data?.message ?? "Unable to load geocoding data.");
    }
  };

  useEffect(() => {
    void loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, statusFilter]);

  useEffect(() => {
    if (activeJobId) {
      void startJobTracking(activeJobId);
    }
  }, [activeJobId, startJobTracking]);

  useEffect(() => {
    if (!job) return;
    if (job.status === "SUCCEEDED") {
      localStorage.removeItem("geocode_job_id");
      setActiveJobId(null);
      toast.success("Geocoding complete", {
        description: job.message ?? "Stop coordinates are updated.",
      });
      void loadData();
    } else if (job.status === "FAILED") {
      localStorage.removeItem("geocode_job_id");
      setActiveJobId(null);
      setError(job.message ?? "Geocoding failed.");
      toast.error("Geocoding failed", {
        description: job.message ?? "Resolve failed stops and retry.",
      });
      void loadData();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status, job?.message]);

  useEffect(() => {
    if (!jobError) return;
    if (activeJobId) {
      localStorage.removeItem("geocode_job_id");
      setActiveJobId(null);
    }
  }, [jobError, activeJobId]);

  const geocodeProgress = useMemo(() => {
    const counts = datasetInfo?.geocode_counts || {};
    const total = Number(datasetInfo?.stop_count || 0);
    const success = Number(counts.SUCCESS || 0) + Number(counts.MANUAL || 0);
    const failed = Number(counts.FAILED || 0);
    const pending = Math.max(total - success - failed, 0);
    const percent = total === 0 ? 0 : Math.round((success / total) * 100);

    return { total, success, failed, pending, percent };
  }, [datasetInfo]);

  const runBatchGeocode = async (failedOnly: boolean, forceAll = false) => {
    if (!datasetId) return;
    try {
      setLoading(true);
      setError(null);
      const accepted = await runGeocoding(datasetId, failedOnly, forceAll);
      setActiveJobId(accepted.job_id);
      localStorage.setItem("geocode_job_id", accepted.job_id);
      await startJobTracking(accepted.job_id);
      toast.info("Geocoding started", {
        description: "Processing in background. You can navigate away and return anytime.",
      });
    } catch (err: any) {
      const msg = err?.response?.data?.message ?? "Geocoding could not complete.";
      setError(msg);
      toast.error("Geocoding failed", {
        description: "Check OneMap connectivity or resolve failed stops manually.",
      });
    } finally {
      setLoading(false);
    }
  };

  const onManualResolve = async () => {
    if (!selectedStop) return;

    try {
      setLoading(true);
      setError(null);
      await manualResolveStop(selectedStop.id, {
        corrected_address: addressInput || null,
        corrected_postal_code: postalInput || null,
        lat: latInput ? Number(latInput) : null,
        lon: lonInput ? Number(lonInput) : null,
      });
      toast.success("Stop resolved", { description: `Stop ${selectedStop.stop_ref} is ready for optimization.` });

      setSelectedStop(null);
      setAddressInput("");
      setPostalInput("");
      setLatInput("");
      setLonInput("");

      await loadData();
    } catch (err: any) {
      const msg = err?.response?.data?.message ?? "Manual resolution failed.";
      setError(msg);
      toast.error("Resolution failed", {
        description: "Check the corrected address or coordinates and try again.",
      });
    } finally {
      setLoading(false);
    }
  };

  if (!datasetId) {
    return (
      <EmptyState
        title="No dataset selected"
        description="Upload and validate a dataset before running geocoding."
        actionLabel="Go to Upload"
        onAction={() => navigate("/upload")}
      />
    );
  }

  const stopCoordinateChecks = useMemo(
    () =>
      stops.map((stop) => ({
        stop,
        coord: checkCoordinate({ lat: stop.lat, lon: stop.lon }),
      })),
    [stops]
  );
  const mapStops = stopCoordinateChecks.filter((entry) => entry.coord.isValid && entry.coord.point);
  const mapPoints = useMemo(() => mapStops.map((entry) => entry.coord.point as [number, number]), [mapStops]);
  const swappedCount = stopCoordinateChecks.filter((entry) => entry.coord.warnings.includes("SWAPPED_INPUT")).length;
  const outOfSingaporeCount = mapStops.filter((entry) => entry.coord.warnings.includes("OUTSIDE_SINGAPORE")).length;
  const invalidCount = stopCoordinateChecks.filter((entry) => !entry.coord.isValid && (entry.stop.lat !== null || entry.stop.lon !== null)).length;
  const mapCenter: [number, number] = mapStops.length > 0 ? (mapStops[0].coord.point as [number, number]) : [1.3521, 103.8198];
  const modalCoordinate = checkCoordinate({
    lat: latInput !== "" ? latInput : selectedStop?.lat,
    lon: lonInput !== "" ? lonInput : selectedStop?.lon,
  });
  const queuedTooLong =
    Boolean(activeJobId) &&
    job?.status === "QUEUED" &&
    Date.now() - new Date(job.updated_at).getTime() > 45_000;
  const isJobBlocking = Boolean(activeJobId) && !queuedTooLong && (!job || job.status === "QUEUED" || job.status === "RUNNING");

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">Geocode stop locations</CardTitle>
          <CardDescription>Resolve coordinates for each stop. Retry failed stops or manually override problematic entries.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
            <div className="rounded-xl border p-3">
              <p className="text-xs uppercase text-muted-foreground">Total stops</p>
              <p className="text-2xl font-bold">{geocodeProgress.total}</p>
            </div>
            <div className="rounded-xl border p-3">
              <p className="text-xs uppercase text-muted-foreground">Geocoded</p>
              <p className="text-2xl font-bold text-success">{geocodeProgress.success}</p>
            </div>
            <div className="rounded-xl border p-3">
              <p className="text-xs uppercase text-muted-foreground">Pending</p>
              <p className="text-2xl font-bold text-warning">{geocodeProgress.pending}</p>
            </div>
            <div className="rounded-xl border p-3">
              <p className="text-xs uppercase text-muted-foreground">Failed</p>
              <p className="text-2xl font-bold text-danger">{geocodeProgress.failed}</p>
            </div>
          </div>

            <div className="space-y-2">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>{activeJobId ? "Job progress" : "Progress"}</span>
              <span>{activeJobId && job ? `${job.progress}%` : `${geocodeProgress.percent}%`}</span>
            </div>
            <Progress value={activeJobId && job ? job.progress : geocodeProgress.percent} />
            {activeJobId && job && <p className="text-xs text-muted-foreground">{job.message}</p>}
          </div>

            <div className="flex flex-wrap gap-2">
            <Button disabled={loading || isJobBlocking} onClick={() => void runBatchGeocode(false)}>
              <Search className="mr-2 h-4 w-4" /> {loading ? "Running geocode..." : "Run geocoding"}
            </Button>
            <Button variant="outline" disabled={loading || isJobBlocking} onClick={() => void runBatchGeocode(true)}>
              <RefreshCcw className="mr-2 h-4 w-4" /> Retry failed stops
            </Button>
            <Button variant="outline" disabled={loading || isJobBlocking} onClick={() => void runBatchGeocode(false, true)}>
              Re-geocode all stops
            </Button>
            {queuedTooLong && (
              <Button
                variant="outline"
                onClick={() => {
                  localStorage.removeItem("geocode_job_id");
                  setActiveJobId(null);
                }}
              >
                Clear stalled job
              </Button>
            )}
              <Button variant="secondary" onClick={() => navigate("/optimization")} disabled={datasetInfo?.geocode_state !== "COMPLETE"}>
                Continue to optimization
              </Button>
            </div>
            {queuedTooLong && (
              <p className="text-xs text-warning">
                Geocoding job is queued for too long. Start `rq worker default --url redis://localhost:6379/0` or rerun now.
              </p>
            )}
          {(outOfSingaporeCount > 0 || invalidCount > 0 || swappedCount > 0) && (
              <div className="flex flex-wrap gap-2">
                {invalidCount > 0 && <Badge variant="danger">Invalid coordinates: {invalidCount}</Badge>}
                {swappedCount > 0 && <Badge variant="warning">Lat/lon swapped and corrected: {swappedCount}</Badge>}
                {outOfSingaporeCount > 0 && <Badge variant="warning">Outside Singapore bounds: {outOfSingaporeCount}</Badge>}
              </div>
            )}
          </CardContent>
        </Card>

      {error && (
        <ErrorState
          title="Geocoding needs attention"
          cause={error}
          nextStep="Retry failed stops or resolve addresses manually, then rerun geocoding."
          actionLabel="Clear error"
          onAction={() => setError(null)}
        />
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <Card>
          <CardHeader className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle>Stops table</CardTitle>
              <Tabs value={statusFilter} onValueChange={setStatusFilter}>
                <TabsList>
                  <TabsTrigger value="all">All</TabsTrigger>
                  <TabsTrigger value="geocoded">Geocoded</TabsTrigger>
                  <TabsTrigger value="failed">Failed</TabsTrigger>
                  <TabsTrigger value="manual">Manual</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
          </CardHeader>
          <CardContent className="max-h-[540px] overflow-auto pt-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ref</TableHead>
                  <TableHead>Address</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Error</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {stops.map((stop) => {
                  const isFailed = stop.geocode_status === "FAILED";
                  const isManual = stop.geocode_status === "MANUAL";

                  return (
                    <TableRow key={stop.id}>
                      <TableCell className="font-medium">{stop.stop_ref}</TableCell>
                      <TableCell className="max-w-[280px] truncate" title={stop.address ?? stop.postal_code ?? "--"}>
                        {stop.address ?? stop.postal_code ?? "--"}
                      </TableCell>
                      <TableCell>
                        <Badge variant={isFailed ? "danger" : isManual ? "warning" : "success"}>{stop.geocode_status.toLowerCase()}</Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {isFailed ? (
                          <span className="inline-flex items-center gap-1">
                            <TriangleAlert className="h-3.5 w-3.5 text-danger" /> {stop.geocode_meta ?? "No detail"}
                          </span>
                        ) : (
                          "-"
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        {(isFailed || stop.geocode_status === "PENDING") && (
                          <Button size="sm" variant="outline" onClick={() => setSelectedStop(stop)}>
                            Resolve
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Map preview</CardTitle>
            <CardDescription>Stops visible for current filter: {stops.length}</CardDescription>
          </CardHeader>
          <CardContent className="h-[540px] pt-0">
            <MapContainer center={mapCenter} zoom={11} className="h-full w-full rounded-xl border">
              <FitMapToStops points={mapPoints} />
              <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="&copy; OpenStreetMap" />
              {mapStops.map((entry, index) => (
                <Marker key={entry.stop.id} position={entry.coord.point as [number, number]} icon={markerLabel(index)}>
                  <Tooltip>
                    <div className="space-y-1 text-xs">
                      <p className="font-semibold">{entry.stop.stop_ref}</p>
                      <p>{entry.stop.address ?? entry.stop.postal_code ?? "No address"}</p>
                      <p>Status: {entry.stop.geocode_status}</p>
                      {entry.coord.warnings.includes("OUTSIDE_SINGAPORE") && <p className="text-warning">Outside SG bounds</p>}
                    </div>
                  </Tooltip>
                </Marker>
              ))}
            </MapContainer>
          </CardContent>
        </Card>
      </div>

      <Dialog open={Boolean(selectedStop)} onOpenChange={(open) => !open && setSelectedStop(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Resolve stop {selectedStop?.stop_ref}</DialogTitle>
            <DialogDescription>Choose corrected search or manual coordinates. Save to mark stop as manually resolved.</DialogDescription>
          </DialogHeader>

          <Tabs value={resolveTab} onValueChange={setResolveTab}>
            <TabsList>
              <TabsTrigger value="search">Correct address</TabsTrigger>
              <TabsTrigger value="manual">Manual coordinates</TabsTrigger>
            </TabsList>

            <TabsContent value="search" className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="corrected_address">Corrected address</Label>
                <Input id="corrected_address" value={addressInput} onChange={(event) => setAddressInput(event.target.value)} placeholder="e.g. 1 Raffles Place" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="corrected_postal">Corrected postal code</Label>
                <Input id="corrected_postal" value={postalInput} onChange={(event) => setPostalInput(event.target.value)} placeholder="e.g. 048616" />
              </div>
            </TabsContent>

            <TabsContent value="manual" className="space-y-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="manual_lat">Latitude</Label>
                  <Input id="manual_lat" value={latInput} onChange={(event) => setLatInput(event.target.value)} placeholder="1.3521" />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="manual_lon">Longitude</Label>
                  <Input id="manual_lon" value={lonInput} onChange={(event) => setLonInput(event.target.value)} placeholder="103.8198" />
                </div>
              </div>

              <div className="h-52 overflow-hidden rounded-xl border">
                <MapContainer
                  center={modalCoordinate.point ?? [1.3521, 103.8198]}
                  zoom={12}
                  className="h-full w-full"
                >
                  <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="&copy; OpenStreetMap" />
                  {modalCoordinate.point ? (
                    <Marker
                      position={modalCoordinate.point as [number, number]}
                      icon={L.divIcon({ className: "", html: `<div class='route-seq-marker'><span><svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='none' stroke='white' stroke-width='2' viewBox='0 0 24 24'><path d='M12 2v20M2 12h20'/></svg></span></div>` })}
                    />
                  ) : null}
                </MapContainer>
              </div>
            </TabsContent>
          </Tabs>

          <div className="flex gap-2">
            <Button onClick={() => void onManualResolve()} disabled={loading}>
              <CheckCircle2 className="mr-2 h-4 w-4" /> Save resolution
            </Button>
            <Button variant="outline" onClick={() => setSelectedStop(null)}>
              Cancel
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
