import L, { DivIcon } from "leaflet";
import { Clock4, Download, FileDown, Navigation2, Route as RouteIcon, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { MapContainer, Marker, Polyline, TileLayer, Tooltip } from "react-leaflet";
import { useNavigate } from "react-router-dom";

import { getDriverCsvUrl, getExportUrl, getMapSnapshotUrl, getPlan } from "../api";
import { DriverRouteSheet } from "../components/results/DriverRouteSheet";
import { RouteCard } from "../components/results/RouteCard";
import { StopCard } from "../components/results/StopCard";
import { EmptyState } from "../components/status/EmptyState";
import { ErrorState } from "../components/status/ErrorState";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Select } from "../components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { useWorkflowContext } from "../components/layout/WorkflowContext";
import type { PlanDetails } from "../types";

const routeColors = ["#109869", "#0f69d5", "#f97316", "#8b5cf6", "#ef4444", "#0ea5a4", "#db2777"];

function seqIcon(sequence: number): DivIcon {
  return L.divIcon({
    className: "",
    html: `<div class='route-seq-marker'>${sequence}</div>`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  });
}

function toTime(iso: string) {
  const dt = new Date(iso);
  return Number.isNaN(dt.getTime()) ? "--:--" : dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function slackRisk(route: PlanDetails["routes"][number]): "low" | "medium" | "high" {
  const slackMins = route.stops
    .filter((stop) => stop.stop_ref !== "DEPOT")
    .map((stop) => {
      const eta = new Date(stop.eta_iso).getTime();
      const end = new Date(stop.arrival_window_end_iso).getTime();
      if (Number.isNaN(eta) || Number.isNaN(end)) return 999;
      return (end - eta) / 60000;
    });

  if (!slackMins.length) return "low";
  const minSlack = Math.min(...slackMins);
  if (minSlack < 10) return "high";
  if (minSlack < 25) return "medium";
  return "low";
}

export function ResultsPage() {
  const navigate = useNavigate();
  const { planId, refresh } = useWorkflowContext();

  const [plan, setPlan] = useState<PlanDetails | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeVehicle, setActiveVehicle] = useState<string>("all");
  const [openStops, setOpenStops] = useState<Record<number, boolean>>({});

  useEffect(() => {
    const load = async () => {
      if (!planId) return;
      try {
        setError(null);
        const data = await getPlan(planId);
        setPlan(data);
        await refresh();
      } catch (err: any) {
        setError(err?.response?.data?.message ?? "Unable to load plan results.");
      }
    };
    void load();
  }, [planId, refresh]);

  const selectedRoutes = useMemo(() => {
    if (!plan) return [];
    if (activeVehicle === "all") return plan.routes;
    return plan.routes.filter((route) => String(route.vehicle_idx) === activeVehicle);
  }, [activeVehicle, plan]);

  const summary = useMemo(() => {
    if (!plan) {
      return {
        servedStops: 0,
        totalStops: 0,
        totalDistance: 0,
        totalDuration: 0,
        finishTime: "--:--",
      };
    }

    const servedStops = plan.routes.reduce(
      (acc, route) => acc + route.stops.filter((stop) => stop.stop_ref !== "DEPOT").length,
      0
    );
    const totalStops = servedStops + plan.unserved_stops.length;
    const totalDistance = plan.routes.reduce((acc, route) => acc + route.total_distance_m, 0);
    const totalDuration = plan.routes.reduce((acc, route) => acc + route.total_duration_s, 0);

    const latestEta = plan.routes
      .flatMap((route) => route.stops.map((stop) => new Date(stop.eta_iso).getTime()))
      .filter((value) => !Number.isNaN(value));
    const finishTime = latestEta.length
      ? new Date(Math.max(...latestEta)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : "--:--";

    return { servedStops, totalStops, totalDistance, totalDuration, finishTime };
  }, [plan]);

  if (!planId) {
    return (
      <EmptyState
        title="No plan selected"
        description="Run optimization first, then view route map, itinerary, and exports here."
        actionLabel="Go to Optimization"
        onAction={() => navigate("/optimization")}
      />
    );
  }

  const mapCenter: [number, number] =
    plan && plan.routes[0]?.stops[0]
      ? [Number(plan.routes[0].stops[0].lat), Number(plan.routes[0].stops[0].lon)]
      : [1.3521, 103.8198];

  return (
    <div className="space-y-4">
      {error && (
        <ErrorState
          title="Results unavailable"
          cause={error}
          nextStep="Re-run optimization or refresh plan ID from top bar."
          actionLabel="Clear"
          onAction={() => setError(null)}
        />
      )}

      {plan && (
        <Tabs defaultValue="planner" className="space-y-3">
          <TabsList className="grid w-full grid-cols-3 sm:w-[420px]">
            <TabsTrigger value="planner">Planner View</TabsTrigger>
            <TabsTrigger value="driver">Driver View</TabsTrigger>
            <TabsTrigger value="exports">Exports</TabsTrigger>
          </TabsList>

          <TabsContent value="planner" className="space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs uppercase text-muted-foreground">Feasibility</p>
                  <div className="mt-1 flex items-center gap-2">
                    <Badge variant={plan.status === "INFEASIBLE" ? "danger" : plan.status === "PARTIAL" ? "warning" : "success"}>
                      {plan.status.toLowerCase()}
                    </Badge>
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs uppercase text-muted-foreground">Stops served</p>
                  <p className="text-xl font-bold">{summary.servedStops} / {summary.totalStops}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs uppercase text-muted-foreground">Total distance</p>
                  <p className="text-xl font-bold">{(summary.totalDistance / 1000).toFixed(1)} km</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs uppercase text-muted-foreground">Total duration</p>
                  <p className="text-xl font-bold">{Math.round(summary.totalDuration / 60)} min</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs uppercase text-muted-foreground">Estimated finish</p>
                  <p className="text-xl font-bold">{summary.finishTime}</p>
                </CardContent>
              </Card>
            </div>

            <div className="grid gap-4 xl:grid-cols-[380px_1fr]">
              <Card className="max-h-[680px] overflow-auto">
                <CardHeader>
                  <CardTitle>Routes</CardTitle>
                  <CardDescription>Select a vehicle to highlight path and stop list.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-2">
                  {plan.routes.map((route) => (
                    <RouteCard
                      key={route.route_id}
                      vehicleIdx={route.vehicle_idx}
                      stopCount={Math.max(0, route.stops.length - 2)}
                      distanceM={route.total_distance_m}
                      durationS={route.total_duration_s}
                      startTime={toTime(route.stops[0]?.eta_iso)}
                      endTime={toTime(route.stops[route.stops.length - 1]?.eta_iso)}
                      selected={activeVehicle !== "all" && String(route.vehicle_idx) === activeVehicle}
                      risk={slackRisk(route)}
                      onClick={() => setActiveVehicle(String(route.vehicle_idx))}
                    />
                  ))}
                  <Button className="w-full" variant="outline" onClick={() => setActiveVehicle("all")}>
                    Show all routes
                  </Button>
                </CardContent>
              </Card>

              <div className="space-y-4">
                <Card>
                  <CardHeader className="flex flex-row items-center justify-between space-y-0">
                    <div>
                      <CardTitle>Map</CardTitle>
                      <CardDescription>Color-coded routes and numbered stops.</CardDescription>
                    </div>
                    <div className="min-w-[180px]">
                      <Select value={activeVehicle} onChange={(event) => setActiveVehicle(event.target.value)}>
                        <option value="all">All vehicles</option>
                        {plan.routes.map((route) => (
                          <option key={route.route_id} value={String(route.vehicle_idx)}>
                            Vehicle {route.vehicle_idx}
                          </option>
                        ))}
                      </Select>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="h-[360px] overflow-hidden rounded-xl border">
                      <MapContainer center={mapCenter} zoom={12}>
                        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="&copy; OpenStreetMap" />
                        {selectedRoutes.map((route, routeIndex) => {
                          const colorIndex = activeVehicle === "all" ? route.vehicle_idx : routeIndex;
                          return (
                            <Polyline
                              key={route.route_id}
                              positions={route.stops.map((stop) => [stop.lat, stop.lon] as [number, number])}
                              pathOptions={{ color: routeColors[colorIndex % routeColors.length], weight: 4, opacity: 0.85 }}
                            />
                          );
                        })}
                        {selectedRoutes.map((route) =>
                          route.stops.map((stop) => (
                            <Marker
                              key={`${route.route_id}-${stop.sequence_idx}`}
                              position={[stop.lat, stop.lon]}
                              icon={seqIcon(stop.sequence_idx)}
                            >
                              <Tooltip>
                                <div className="space-y-1 text-xs">
                                  <p className="font-semibold">{stop.stop_ref}</p>
                                  <p>{stop.address}</p>
                                  <p>ETA {toTime(stop.eta_iso)}</p>
                                  <p>
                                    TW {toTime(stop.arrival_window_start_iso)} - {toTime(stop.arrival_window_end_iso)}
                                  </p>
                                  <p>Service {toTime(stop.service_start_iso)} - {toTime(stop.service_end_iso)}</p>
                                </div>
                              </Tooltip>
                            </Marker>
                          ))
                        )}
                      </MapContainer>
                    </div>

                    <div className="flex flex-wrap gap-3 text-xs">
                      {selectedRoutes.map((route, index) => (
                        <span key={route.route_id} className="inline-flex items-center gap-2 rounded-full border px-3 py-1">
                          <span
                            className="h-2.5 w-2.5 rounded-full"
                            style={{ backgroundColor: routeColors[(activeVehicle === "all" ? route.vehicle_idx : index) % routeColors.length] }}
                          />
                          Vehicle {route.vehicle_idx}
                        </span>
                      ))}
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Stop list</CardTitle>
                    <CardDescription>Expand routes for sequence, ETA, and time windows.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {selectedRoutes.map((route) => {
                      const expanded = openStops[route.route_id] ?? true;
                      return (
                        <div key={route.route_id} className="space-y-2 rounded-xl border p-3">
                          <div className="flex items-center justify-between">
                            <p className="text-sm font-semibold">Vehicle {route.vehicle_idx}</p>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setOpenStops((prev) => ({ ...prev, [route.route_id]: !expanded }))}
                            >
                              {expanded ? "Collapse" : "Expand"}
                            </Button>
                          </div>
                          {expanded && (
                            <div className="space-y-2">
                              {route.stops.map((stop) => (
                                <StopCard
                                  key={`${route.route_id}-${stop.sequence_idx}-stop-card`}
                                  sequence={stop.sequence_idx}
                                  stopRef={stop.stop_ref}
                                  address={stop.address}
                                  eta={toTime(stop.eta_iso)}
                                  timeWindow={`${toTime(stop.arrival_window_start_iso)} - ${toTime(stop.arrival_window_end_iso)}`}
                                  serviceTime={`${toTime(stop.service_start_iso)} - ${toTime(stop.service_end_iso)}`}
                                  isDepot={stop.stop_ref === "DEPOT"}
                                />
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </CardContent>
                </Card>
              </div>
            </div>

            {plan.unserved_stops.length > 0 && (
              <Card className="border-warning/50 bg-warning/5">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-warning">
                    <TriangleAlert className="h-5 w-5" /> Unserved stops
                  </CardTitle>
                  <CardDescription>These stops were not assigned in the final plan.</CardDescription>
                </CardHeader>
                <CardContent>
                  <ul className="space-y-1 text-sm">
                    {plan.unserved_stops.map((stop) => (
                      <li key={stop.stop_id}>
                        <span className="font-semibold">{stop.stop_ref}</span> - {stop.address}
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          <TabsContent value="driver" className="space-y-4">
            <Card className="no-print">
              <CardHeader>
                <CardTitle>Driver route view</CardTitle>
                <CardDescription>Mobile-first layout with large text and clear action buttons.</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                <Select value={activeVehicle} onChange={(event) => setActiveVehicle(event.target.value)} className="w-44">
                  <option value="all">All vehicles</option>
                  {plan.routes.map((route) => (
                    <option key={route.route_id} value={String(route.vehicle_idx)}>
                      Vehicle {route.vehicle_idx}
                    </option>
                  ))}
                </Select>
                <Button variant="outline" onClick={() => window.print()}>
                  <FileDown className="mr-2 h-4 w-4" /> Print driver view
                </Button>
              </CardContent>
            </Card>

            {selectedRoutes.map((route) => (
              <DriverRouteSheet
                key={`driver-${route.route_id}`}
                vehicleIdx={route.vehicle_idx}
                stops={route.stops}
                totalDistanceM={route.total_distance_m}
                totalDurationS={route.total_duration_s}
              />
            ))}
          </TabsContent>

          <TabsContent value="exports" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>Export center</CardTitle>
                <CardDescription>Generate route packs for planners and drivers.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <Button size="lg" onClick={() => window.open(getExportUrl(plan.plan_id, "pdf", { profile: "driver" }), "_blank")}>
                    <Download className="mr-2 h-4 w-4" /> Download Combined Driver Pack (PDF)
                  </Button>
                  <Button size="lg" variant="outline" onClick={() => window.open(getExportUrl(plan.plan_id, "csv", { profile: "planner" }), "_blank")}>
                    <Download className="mr-2 h-4 w-4" /> Download Planner CSV
                  </Button>
                  <Button size="lg" variant="outline" onClick={() => window.open(getDriverCsvUrl(plan.plan_id), "_blank")}>
                    <Download className="mr-2 h-4 w-4" /> Download Driver CSV
                  </Button>
                  <Button size="lg" variant="secondary" onClick={() => window.open(getMapSnapshotUrl(plan.plan_id), "_blank")}>
                    <Navigation2 className="mr-2 h-4 w-4" /> Preview map snapshot
                  </Button>
                </div>

                <div className="space-y-2 rounded-xl border bg-muted/20 p-4 text-sm">
                  <p className="font-semibold">PDF includes</p>
                  <ul className="list-disc space-y-1 pl-4 text-muted-foreground">
                    <li>Cover page with route overview map and total route summary</li>
                    <li>Per-vehicle route sheets with ETA, time windows, service window, and notes</li>
                    <li>Readable headers/footers for print and mobile viewing</li>
                    <li>Route-level navigation QR code</li>
                  </ul>
                </div>

                <div className="space-y-2">
                  <p className="text-sm font-semibold">Per-vehicle PDF</p>
                  <div className="flex flex-wrap gap-2">
                    {plan.routes.map((route) => (
                      <Button
                        key={`pdf-${route.route_id}`}
                        variant="outline"
                        onClick={() =>
                          window.open(getExportUrl(plan.plan_id, "pdf", { profile: "driver", vehicleIdx: route.vehicle_idx }), "_blank")
                        }
                      >
                        <RouteIcon className="mr-2 h-4 w-4" /> Vehicle {route.vehicle_idx}
                      </Button>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      )}

      <div className="print-only rounded-lg border p-4">
        <p className="text-sm text-muted-foreground">Printed from Driver View. Use Planner View for map interaction.</p>
      </div>
    </div>
  );
}
