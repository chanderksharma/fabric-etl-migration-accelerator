import type { ColumnMetadataMap } from "@/lib/to-data-table";
import query from "./assessment-runs.dax?raw";

export const connection = "assessmentmodel";

export { query };

export const columnMetadata: ColumnMetadataMap = {
  "AssessmentRun[RunId]": { name: "RunId", displayName: "Run ID" },
  "AssessmentRun[RunLabel]": { name: "RunLabel", displayName: "Run" },
  "AssessmentRun[StartedAtUtc]": { name: "StartedAtUtc", displayName: "Started" },
  "AssessmentRun[CompletedAtUtc]": { name: "CompletedAtUtc", displayName: "Completed" },
  "AssessmentRun[Status]": { name: "Status", displayName: "Status" },
  "AssessmentRun[WorkflowCount]": { name: "WorkflowCount", displayName: "Workflows", format: "#,##0" },
  "AssessmentRun[FailedCount]": { name: "FailedCount", displayName: "Failed", format: "#,##0" },
  "AssessmentRun[SkippedCount]": { name: "SkippedCount", displayName: "Skipped", format: "#,##0" },
  "AssessmentRun[RulesVersion]": { name: "RulesVersion", displayName: "Rules version" },
};
