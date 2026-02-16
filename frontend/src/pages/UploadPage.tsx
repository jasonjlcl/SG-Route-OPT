import { AlertCircle, Download, FileSpreadsheet, UploadCloud } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { getValidationErrorLogUrl, uploadDataset } from "../api";
import { useWorkflowContext } from "../components/layout/WorkflowContext";
import { ErrorState } from "../components/status/ErrorState";
import { LoadingState } from "../components/status/LoadingState";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Skeleton } from "../components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../components/ui/tooltip";
import type { UploadResponse } from "../types";

const TEMPLATE_CONTENT = `stop_ref,address,postal_code,demand,service_time_min,tw_start,tw_end,phone,contact_name\nS1,10 Bayfront Avenue,,1,5,09:00,12:00,+65 81234567,Jason Tan\nS2,1 Raffles Place,,2,8,10:00,15:30,,\nS3,,768024,1,6,09:30,16:00,91234567,Ops Desk\n`;

export function UploadPage() {
  const navigate = useNavigate();
  const { setDatasetId, refresh } = useWorkflowContext();

  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResponse | null>(() => {
    const raw = localStorage.getItem("last_upload_result");
    return raw ? (JSON.parse(raw) as UploadResponse) : null;
  });

  const fileMeta = useMemo(() => {
    if (!file) return "No file selected";
    const kb = file.size / 1024;
    return `${file.name} (${kb.toFixed(1)} KB)`;
  }, [file]);

  const canContinueToGeocoding = useMemo(() => {
    if (!result) return false;
    return result.next_action === "RUN_GEOCODING" && result.validation_summary.valid_rows_count > 0;
  }, [result]);

  const onUpload = async (excludeInvalid: boolean) => {
    if (!file) {
      setError("Select a CSV or XLSX file to start validation.");
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const data = await uploadDataset(file, excludeInvalid);
      setResult(data);
      localStorage.setItem("last_upload_result", JSON.stringify(data));
      setDatasetId(data.dataset_id);
      await refresh();

      toast.success("File validated", {
        description: `${data.validation_summary.valid_rows_count} valid rows ready for geocoding.`,
      });

      if (data.next_action === "RUN_GEOCODING") {
        navigate("/geocoding");
      }
    } catch (err: any) {
      const msg = err?.response?.data?.message ?? "Upload failed. Check template format and required columns.";
      setError(msg);
      toast.error("Upload failed", {
        description: "Review file structure and try again.",
      });
    } finally {
      setLoading(false);
    }
  };

  const downloadTemplate = () => {
    const blob = new Blob([TEMPLATE_CONTENT], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "stops_template.csv";
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-5">
      <Card className="overflow-hidden">
        <CardHeader className="bg-gradient-to-r from-primary/10 via-primary/5 to-transparent">
          <CardTitle className="text-2xl">Upload delivery stops</CardTitle>
          <CardDescription>
            Start your planning workflow by uploading a stop list. We will validate format, time windows, and row-level quality.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 pt-5">
          <div
            className={`rounded-xl border-2 border-dashed p-8 text-center transition ${
              dragging ? "border-primary bg-primary/5" : "border-border bg-muted/20"
            }`}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              const dropped = event.dataTransfer.files?.[0];
              if (dropped) setFile(dropped);
            }}
          >
            <UploadCloud className="mx-auto mb-3 h-10 w-10 text-primary" />
            <p className="text-base font-semibold">Drag and drop CSV/XLSX here</p>
            <p className="mt-1 text-sm text-muted-foreground">or browse from your computer</p>
            <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
              <input
                id="upload-file-input"
                type="file"
                accept=".csv,.xlsx"
                className="hidden"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
              <Button variant="secondary" onClick={() => document.getElementById("upload-file-input")?.click()}>
                <FileSpreadsheet className="mr-2 h-4 w-4" /> Choose file
              </Button>
              <Button variant="outline" onClick={downloadTemplate}>
                <Download className="mr-2 h-4 w-4" /> Download template
              </Button>
            </div>
            <p className="mt-3 text-xs text-muted-foreground">{fileMeta}</p>
          </div>

          <details className="rounded-xl border bg-muted/20 p-4 text-sm">
            <summary className="cursor-pointer font-semibold">File requirements</summary>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-muted-foreground">
              <li>Required columns: <code>stop_ref</code>, and at least one of <code>address</code> or <code>postal_code</code>.</li>
              <li>Optional columns: <code>demand</code>, <code>service_time_min</code>, <code>tw_start</code>, <code>tw_end</code>, <code>phone</code>, <code>contact_name</code>.</li>
              <li>Time format must be HH:MM (24-hour).</li>
              <li>Demand and service time must be non-negative integers.</li>
            </ul>
          </details>

          <div className="flex flex-wrap gap-2">
            <Button size="lg" disabled={loading || !file} onClick={() => void onUpload(false)}>
              {loading ? "Validating..." : "Upload & validate"}
            </Button>
            <Button size="lg" variant="outline" disabled={loading || !file} onClick={() => void onUpload(true)}>
              Proceed with valid stops
            </Button>
          </div>
        </CardContent>
      </Card>

      {loading && <LoadingState title="Uploading and validating" />}

      {error && (
        <ErrorState
          title="Validation could not be completed"
          cause={error}
          nextStep="Check required columns and row formats, then retry upload."
          actionLabel="Try upload again"
          onAction={() => setError(null)}
        />
      )}

      {result && !loading && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Validation summary
              {result.validation_summary.invalid_rows_count > 0 ? (
                <Badge variant="warning">Needs attention</Badge>
              ) : (
                <Badge variant="success">Ready</Badge>
              )}
            </CardTitle>
            <CardDescription>Review quality checks and decide whether to proceed.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="rounded-xl border p-4">
                <p className="text-xs uppercase text-muted-foreground">Valid rows</p>
                <p className="text-2xl font-bold text-success">{result.validation_summary.valid_rows_count}</p>
              </div>
              <div className="rounded-xl border p-4">
                <p className="text-xs uppercase text-muted-foreground">Invalid rows</p>
                <p className="text-2xl font-bold text-danger">{result.validation_summary.invalid_rows_count}</p>
              </div>
              <div className="rounded-xl border p-4">
                <p className="text-xs uppercase text-muted-foreground">Next action</p>
                <p className="text-base font-semibold">{result.next_action.split("_").join(" ")}</p>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              {result.validation_summary.invalid_rows_count > 0 && (
                <Button variant="secondary" onClick={() => window.open(getValidationErrorLogUrl(result.dataset_id), "_blank")}>
                  <Download className="mr-2 h-4 w-4" /> Download error log CSV
                </Button>
              )}
              <Button onClick={() => navigate("/geocoding")} disabled={!canContinueToGeocoding}>
                Continue to geocoding
              </Button>
            </div>

            {result.validation_summary.invalid_rows_count > 0 ? (
              <div className="rounded-xl border">
                <div className="flex items-center gap-2 border-b px-4 py-3 text-sm font-semibold">
                  <AlertCircle className="h-4 w-4 text-warning" /> Invalid rows preview
                </div>
                <div className="max-h-72 overflow-auto">
                  <TooltipProvider>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Row</TableHead>
                          <TableHead>Reason</TableHead>
                          <TableHead>Status</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {result.validation_summary.invalid_rows.slice(0, 40).map((issue) => (
                          <TableRow key={`${issue.row_index}-${issue.reason}`}>
                            <TableCell>{issue.row_index}</TableCell>
                            <TableCell className="max-w-[600px]">
                              <Tooltip>
                                <TooltipTrigger className="cursor-help text-left text-sm text-muted-foreground">
                                  {issue.reason.length > 120 ? `${issue.reason.slice(0, 120)}...` : issue.reason}
                                </TooltipTrigger>
                                <TooltipContent className="max-w-xs">{issue.reason}</TooltipContent>
                              </Tooltip>
                            </TableCell>
                            <TableCell>
                              <Badge variant="danger">Invalid</Badge>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TooltipProvider>
                </div>
              </div>
            ) : (
              <div className="rounded-xl border bg-success/10 p-4 text-sm text-success">
                All rows are valid. Proceed to geocoding to resolve coordinates and continue route planning.
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {!result && !loading && (
        <div className="grid gap-3 md:grid-cols-3">
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-24 rounded-xl" />
        </div>
      )}
    </div>
  );
}
