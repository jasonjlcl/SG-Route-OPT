import { Clock4, MapPin, Timer } from "lucide-react";

import { Badge } from "../ui/badge";
import { Card, CardContent } from "../ui/card";
import { cn } from "../../lib/utils";

type RouteCardProps = {
  vehicleIdx: number;
  stopCount: number;
  distanceM: number;
  durationS: number;
  startTime?: string;
  endTime?: string;
  selected?: boolean;
  risk: "low" | "medium" | "high";
  onClick?: () => void;
};

export function RouteCard({ vehicleIdx, stopCount, distanceM, durationS, startTime, endTime, selected, risk, onClick }: RouteCardProps) {
  return (
    <Card
      className={cn(
        "cursor-pointer border transition",
        selected ? "border-primary bg-primary/5" : "hover:border-primary/50"
      )}
      onClick={onClick}
    >
      <CardContent className="space-y-3 p-4">
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-semibold">Vehicle {vehicleIdx}</h4>
          <Badge variant={risk === "high" ? "danger" : risk === "medium" ? "warning" : "success"}>{risk} risk</Badge>
        </div>

        <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground md:grid-cols-4">
          <div className="flex items-center gap-1">
            <MapPin className="h-3.5 w-3.5" /> {stopCount} stops
          </div>
          <div className="flex items-center gap-1">
            <Timer className="h-3.5 w-3.5" /> {(distanceM / 1000).toFixed(1)} km
          </div>
          <div className="flex items-center gap-1">
            <Clock4 className="h-3.5 w-3.5" /> {Math.round(durationS / 60)} min
          </div>
          <div className="text-right text-xs">
            {startTime && endTime ? `${startTime} - ${endTime}` : "No shift window"}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
