import { useEffect, useMemo, useState } from "react";
import { MapContainer, Marker, Polyline, TileLayer } from "react-leaflet";
import { useSearchParams } from "react-router-dom";

import { getPlan } from "../api";
import { checkCoordinate } from "../lib/geo";
import type { PlanDetails } from "../types";

const routeColors = ["#109869", "#0f69d5", "#f97316", "#8b5cf6", "#ef4444", "#0ea5a4", "#db2777"];

export function PrintMapPage() {
  const [params] = useSearchParams();
  const [plan, setPlan] = useState<PlanDetails | null>(null);
  const [tilesReady, setTilesReady] = useState(false);

  const planId = Number(params.get("plan_id") || "0");
  const mode = params.get("mode") === "single" ? "single" : "all";
  const routeId = Number(params.get("route_id") || "0");

  useEffect(() => {
    const load = async () => {
      if (!planId) return;
      const data = await getPlan(planId);
      setPlan(data);
    };
    void load();
  }, [planId]);

  const routes = useMemo(() => {
    if (!plan) return [];
    if (mode !== "single" || !routeId) return plan.routes;
    return plan.routes.filter((route) => route.route_id === routeId);
  }, [mode, plan, routeId]);

  const points = useMemo(
    () =>
      routes.flatMap((route) =>
        route.stops
          .map((stop) => checkCoordinate({ lat: stop.lat, lon: stop.lon }).point)
          .filter((point): point is [number, number] => Array.isArray(point))
      ),
    [routes]
  );

  const center: [number, number] = points[0] ?? [1.3521, 103.8198];
  const ready = Boolean(plan) && (points.length === 0 || tilesReady);

  return (
    <div id="print-map-root" style={{ width: "1400px", height: "900px", background: "white", padding: 16, boxSizing: "border-box" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10, fontFamily: "Inter, Arial, sans-serif" }}>
        <strong>Route Map - Plan #{planId}</strong>
        <span>{mode === "single" ? `Route ${routeId}` : "All routes"}</span>
      </div>
      <div id="print-map-ready" data-ready={ready ? "1" : "0"} style={{ display: "none" }} />
      <div style={{ height: "840px", border: "1px solid #dbe2ea", borderRadius: 12, overflow: "hidden" }}>
        <MapContainer center={center} zoom={12} style={{ width: "100%", height: "100%" }}>
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution="&copy; OpenStreetMap contributors"
            eventHandlers={{
              load: () => setTilesReady(true),
              loading: () => setTilesReady(false),
              tileerror: () => setTilesReady(false),
            }}
          />
          {routes.map((route, index) => {
            const path = route.stops
              .map((stop) => checkCoordinate({ lat: stop.lat, lon: stop.lon }).point)
              .filter((point): point is [number, number] => Array.isArray(point));
            if (path.length < 2) return null;
            return <Polyline key={route.route_id} positions={path} pathOptions={{ color: routeColors[index % routeColors.length], weight: 4 }} />;
          })}
          {routes.map((route, index) =>
            route.stops.map((stop) => {
              const point = checkCoordinate({ lat: stop.lat, lon: stop.lon }).point;
              if (!point) return null;
              return <Marker key={`${route.route_id}-${stop.sequence_idx}-${index}`} position={point} />;
            })
          )}
        </MapContainer>
      </div>
    </div>
  );
}
