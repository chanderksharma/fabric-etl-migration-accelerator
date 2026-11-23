import { createContext, useContext } from "react";

export interface AssessmentRunOption {
  runId: string;
  runLabel: string;
  startedAtUtc: string;
  completedAtUtc: string;
  workflowCount: number;
  failedCount: number;
  skippedCount: number;
  rulesVersion: string;
  inputPath: string;
  routingBasis: "static_mapping" | "compiler_confirmed";
}

export interface RefreshAssessmentRunsOptions {
  selectLatest?: boolean;
}

export interface AssessmentRunContextValue {
  activeRunId: string | null;
  runs: AssessmentRunOption[];
  isLoading: boolean;
  error?: Error;
  revision: number;
  selectRun: (runId: string | null) => void;
  refreshRuns: (options?: RefreshAssessmentRunsOptions) => Promise<void>;
}

const defaultValue: AssessmentRunContextValue = {
  activeRunId: null,
  runs: [],
  isLoading: false,
  revision: 0,
  selectRun: () => undefined,
  refreshRuns: async () => undefined,
};

export const AssessmentRunContext = createContext<AssessmentRunContextValue>(defaultValue);

export function useAssessmentRunContext(): AssessmentRunContextValue {
  return useContext(AssessmentRunContext);
}
