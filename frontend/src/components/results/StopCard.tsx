import { Clock4, Flag, MapPin } from "lucide-react";

import { Badge } from "../ui/badge";
import { Card, CardContent } from "../ui/card";

type StopCardProps = {
  sequence: number;
  stopRef: string;
  address: string;
  eta: string;
  timeWindow: string;
  serviceTime: string;
  isDepot?: boolean;
};

export function StopCard({ sequence, stopRef, address, eta, timeWindow, serviceTime, isDepot }: StopCardProps) {
  return (
    <Card className="border-border/80">
      <CardContent className="flex gap-3 p-4">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
          {sequence}
        </div>
        <div className="w-full space-y-2">
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className="text-sm font-semibold">{stopRef}</p>
              <p className="text-xs text-muted-foreground">{address}</p>
            </div>
            {isDepot ? <Badge variant="muted">Depot</Badge> : <Badge variant="outline">Stop</Badge>}
          </div>
          <div className="grid grid-cols-1 gap-1 text-xs text-muted-foreground sm:grid-cols-3">
            <p className="flex items-center gap-1">
              <Clock4 className="h-3.5 w-3.5" /> ETA {eta}
            </p>
            <p className="flex items-center gap-1">
              <Flag className="h-3.5 w-3.5" /> TW {timeWindow}
            </p>
            <p className="flex items-center gap-1">
              <MapPin className="h-3.5 w-3.5" /> Service {serviceTime}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
