import { CheckCircle2, CircleDashed, Clock3, AlertTriangle } from "lucide-react";
import type { ComponentType } from "react";
import { Link, useLocation } from "react-router-dom";

import type { StepStatus, WorkflowStep } from "../../hooks/useWorkflowState";
import { cn } from "../../lib/utils";

const statusMeta: Record<StepStatus, { icon: ComponentType<{ className?: string }>; label: string; className: string }> = {
  not_started: { icon: CircleDashed, label: "Not started", className: "text-muted-foreground" },
  in_progress: { icon: Clock3, label: "In progress", className: "text-warning" },
  complete: { icon: CheckCircle2, label: "Complete", className: "text-success" },
  attention: { icon: AlertTriangle, label: "Needs attention", className: "text-danger" },
};

export function StepNav({ steps }: { steps: WorkflowStep[] }) {
  const location = useLocation();

  return (
    <nav className="space-y-2">
      {steps.map((step, index) => {
        const active = location.pathname === step.route;
        const meta = statusMeta[step.status];
        const Icon = meta.icon;

        return (
          <Link
            key={step.key}
            to={step.route}
            className={cn(
              "flex items-center justify-between rounded-xl border px-3 py-3 transition",
              active ? "border-primary bg-primary/10" : "border-border bg-card hover:border-primary/40"
            )}
          >
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-muted text-sm font-semibold">{index + 1}</div>
              <div>
                <p className="text-sm font-semibold">{step.label}</p>
                <p className="text-xs text-muted-foreground">{meta.label}</p>
              </div>
            </div>
            <Icon className={cn("h-4 w-4", meta.className)} />
          </Link>
        );
      })}
    </nav>
  );
}
