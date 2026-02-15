import { Copy, Navigation } from "lucide-react";

import { Button } from "../ui/button";
import { Card, CardContent } from "../ui/card";

type DriverStop = {
  sequence_idx: number;
  stop_ref: string;
  address: string;
  eta_iso: string;
  arrival_window_start_iso: string;
  arrival_window_end_iso: string;
  service_start_iso: string;
  service_end_iso: string;
  lat: number;
  lon: number;
};

type DriverRouteSheetProps = {
  vehicleIdx: number;
  stops: DriverStop[];
  totalDistanceM: number;
  totalDurationS: number;
};

function fmtTime(value: string) {
  const dt = new Date(value);
  return Number.isNaN(dt.getTime()) ? "--:--" : dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function DriverRouteSheet({ vehicleIdx, stops, totalDistanceM, totalDurationS }: DriverRouteSheetProps) {
  const openNav = (lat: number, lon: number) => {
    window.open(`https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`, "_blank");
  };

  const copyAddress = async (address: string) => {
    try {
      await navigator.clipboard.writeText(address);
    } catch {
      // no-op
    }
  };

  return (
    <section className="driver-print-sheet space-y-4">
      <Card className="sticky top-16 z-10 border-primary/30 bg-primary/5">
        <CardContent className="space-y-2 p-4">
          <h3 className="text-xl font-bold">Vehicle {vehicleIdx} Route Sheet</h3>
          <p className="text-sm text-muted-foreground">
            {Math.max(0, stops.length - 2)} stops • {(totalDistanceM / 1000).toFixed(1)} km • {Math.round(totalDurationS / 60)} min
          </p>
        </CardContent>
      </Card>

      {stops.map((stop) => (
        <Card key={`${vehicleIdx}-${stop.sequence_idx}`} className="border-border/80">
          <CardContent className="space-y-3 p-4">
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary text-base font-bold text-primary-foreground">
                  {stop.sequence_idx}
                </div>
                <div>
                  <p className="text-lg font-semibold">{stop.stop_ref}</p>
                  <p className="text-sm text-muted-foreground">{stop.address}</p>
                </div>
              </div>
              <div className="text-right">
                <p className="text-xs text-muted-foreground">Planned ETA</p>
                <p className="text-2xl font-bold text-primary">{fmtTime(stop.eta_iso)}</p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 text-sm">
              <p>
                <span className="font-semibold">Window:</span> {fmtTime(stop.arrival_window_start_iso)} - {fmtTime(stop.arrival_window_end_iso)}
              </p>
              <p>
                <span className="font-semibold">Service:</span> {fmtTime(stop.service_start_iso)} - {fmtTime(stop.service_end_iso)}
              </p>
            </div>

            <div className="grid grid-cols-2 gap-2 sm:flex sm:gap-3">
              <Button className="h-11" onClick={() => openNav(stop.lat, stop.lon)}>
                <Navigation className="mr-2 h-4 w-4" /> Navigate
              </Button>
              <Button className="h-11" variant="outline" onClick={() => void copyAddress(stop.address)}>
                <Copy className="mr-2 h-4 w-4" /> Copy address
              </Button>
            </div>
          </CardContent>
        </Card>
      ))}
    </section>
  );
}
