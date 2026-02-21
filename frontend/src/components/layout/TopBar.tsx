import { Download, RefreshCcw } from "lucide-react";
import { Link } from "react-router-dom";

import { getExportUrl } from "../../api";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Input } from "../ui/input";

type TopBarProps = {
  datasetId: number;
  planId: number;
  datasetStatus: string;
  onDatasetChange: (id: number) => void;
  onRefresh: () => Promise<void>;
  refreshing?: boolean;
};

export function TopBar({ datasetId, planId, datasetStatus, onDatasetChange, onRefresh, refreshing = false }: TopBarProps) {
  return (
    <header className="no-print sticky top-0 z-20 border-b bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/90">
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div>
          <h1 className="text-xl font-semibold">RouteOps SG</h1>
          <p className="text-xs text-muted-foreground">Plan, optimize, and dispatch routes with confidence.</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Link to="/ml" className="text-sm text-primary underline-offset-2 hover:underline">
            ML Settings
          </Link>
          <Link to="/evaluation" className="text-sm text-primary underline-offset-2 hover:underline">
            Evaluation
          </Link>
          <div className="flex items-center gap-2 rounded-lg border bg-background px-2 py-1">
            <span className="text-xs text-muted-foreground">Dataset</span>
            <Input
              className="h-8 w-24 border-0 bg-transparent p-0 text-sm"
              value={datasetId || ""}
              onChange={(event) => {
                const parsed = Number(event.target.value);
                onDatasetChange(Number.isFinite(parsed) ? parsed : 0);
              }}
              placeholder="ID"
            />
          </div>

          <Badge variant={datasetStatus === "OPTIMIZED" ? "success" : datasetStatus.includes("FAILED") ? "danger" : "warning"}>
            {datasetStatus || "No dataset"}
          </Badge>

          <Button variant="secondary" size="sm" onClick={() => void onRefresh()} disabled={refreshing}>
            <RefreshCcw className={`mr-2 h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
            {refreshing ? "Refreshing..." : "Refresh"}
          </Button>

          {planId > 0 && (
            <>
              <Button size="sm" variant="outline" onClick={() => window.open(getExportUrl(planId, "csv"), "_blank")}>
                <Download className="mr-2 h-4 w-4" /> Planner CSV
              </Button>
              <Button size="sm" onClick={() => window.open(getExportUrl(planId, "pdf"), "_blank")}>
                <Download className="mr-2 h-4 w-4" /> Driver Pack PDF
              </Button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
