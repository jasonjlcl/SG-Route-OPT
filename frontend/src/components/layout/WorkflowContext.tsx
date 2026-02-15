import { createContext, useContext } from "react";
import type React from "react";

import { useWorkflowState } from "../../hooks/useWorkflowState";

type WorkflowContextValue = ReturnType<typeof useWorkflowState>;

const WorkflowContext = createContext<WorkflowContextValue | null>(null);

export function WorkflowProvider({ children }: { children: React.ReactNode }) {
  const value = useWorkflowState();
  return <WorkflowContext.Provider value={value}>{children}</WorkflowContext.Provider>;
}

export function useWorkflowContext() {
  const ctx = useContext(WorkflowContext);
  if (!ctx) {
    throw new Error("useWorkflowContext must be used within WorkflowProvider");
  }
  return ctx;
}
