import { useMemo } from "react";
import { useNavigate } from "react-router-dom";

import { useWorkflowContext } from "../components/layout/WorkflowContext";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { EmptyState } from "../components/status/EmptyState";

export function ValidationPage() {
  const navigate = useNavigate();
  const { datasetId, dataset } = useWorkflowContext();

  const geocodeSummary = useMemo(() => {
    const counts = dataset?.geocode_counts || {};
    return {
      success: Number(counts.SUCCESS || 0) + Number(counts.MANUAL || 0),
      failed: Number(counts.FAILED || 0),
      pending: Number(counts.PENDING || 0),
    };
  }, [dataset]);
  const canContinueToGeocoding =
    (dataset?.validation_state === "VALID" || dataset?.validation_state === "PARTIAL") && Number(dataset?.valid_stop_count || 0) > 0;

  if (!datasetId) {
    return <EmptyState title="No dataset yet" description="Upload a CSV or XLSX file first to run validation." actionLabel="Go to Upload" onAction={() => (window.location.href = "/upload")} />;
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Validation & Dataset Health</CardTitle>
          <CardDescription>Review dataset quality before geocoding and optimization.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div className="rounded-lg border bg-muted/50 p-3">
              <p className="text-xs text-muted-foreground">Dataset ID</p>
              <p className="text-lg font-semibold">{datasetId}</p>
            </div>
            <div className="rounded-lg border bg-muted/50 p-3">
              <p className="text-xs text-muted-foreground">File name</p>
              <p className="truncate text-sm font-medium">{dataset?.filename || "--"}</p>
            </div>
            <div className="rounded-lg border bg-muted/50 p-3">
              <p className="text-xs text-muted-foreground">Validation state</p>
              <Badge
                variant={
                  dataset?.validation_state === "VALID" || dataset?.validation_state === "PARTIAL"
                    ? "success"
                    : dataset?.validation_state === "BLOCKED"
                      ? "danger"
                      : "warning"
                }
              >
                {dataset?.validation_state || "NOT_STARTED"}
              </Badge>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Geocoded</p>
              <p className="text-2xl font-semibold text-success">{geocodeSummary.success}</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Pending geocode</p>
              <p className="text-2xl font-semibold text-warning">{geocodeSummary.pending}</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Failed geocode</p>
              <p className="text-2xl font-semibold text-danger">{geocodeSummary.failed}</p>
            </div>
          </div>

          <div className="flex gap-2">
            <Button onClick={() => navigate("/geocoding")} disabled={!canContinueToGeocoding}>
              Continue to Geocoding
            </Button>
            <Button variant="outline" onClick={() => navigate("/upload")}>Upload another file</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
