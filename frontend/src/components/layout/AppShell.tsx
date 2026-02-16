import { Outlet } from "react-router-dom";

import { useWorkflowContext } from "./WorkflowContext";
import { StepNav } from "./StepNav";
import { TopBar } from "./TopBar";

export function AppShell() {
  const { datasetId, planId, dataset, steps, setDatasetId, refresh } = useWorkflowContext();

  return (
    <div className="min-h-screen">
      <TopBar
        datasetId={datasetId}
        planId={planId}
        datasetStatus={String(dataset?.status || "No dataset")}
        onDatasetChange={setDatasetId}
        onRefresh={refresh}
      />
      <div className="mx-auto grid max-w-[1400px] grid-cols-1 gap-6 p-4 md:grid-cols-[260px_1fr]">
        <aside className="no-print rounded-xl border bg-card p-4 shadow-soft">
          <p className="mb-3 text-sm font-semibold">Workflow</p>
          <StepNav steps={steps} />
        </aside>
        <main className="min-h-[calc(100vh-120px)]">
          <Outlet />
        </main>
      </div>
      <footer className="pb-6 text-center text-xs text-muted-foreground">
        Developed by Jason Lim
      </footer>
    </div>
  );
}
