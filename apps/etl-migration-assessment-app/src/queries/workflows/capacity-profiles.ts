import type { ColumnMetadataMap } from "@/lib/to-data-table";
import query from "./capacity-profiles.dax?raw";

export const connection = "assessmentmodel";

export { query };

export const columnMetadata: ColumnMetadataMap = {
  "CapacityProfile[WorkflowKey]": { name: "WorkflowKey", displayName: "Workflow key" },
  "CapacityProfile[ProfileKind]": { name: "ProfileKind", displayName: "Profile kind" },
  "CapacityProfile[TargetComponents]": { name: "TargetComponents", displayName: "Target components" },
  "CapacityProfile[ComplexityUnits]": { name: "ComplexityUnits", displayName: "Complexity units", format: "#,##0.00" },
  "CapacityProfile[DestCount]": { name: "DestCount", displayName: "Outputs", format: "#,##0" },
  "CapacityProfile[HeavySteps]": { name: "HeavySteps", displayName: "Heavy steps", format: "#,##0" },
  "CapacityProfile[NotebookSteps]": { name: "NotebookSteps", displayName: "Notebook steps", format: "#,##0" },
  "CapacityProfile[PipelineSteps]": { name: "PipelineSteps", displayName: "Pipeline steps", format: "#,##0" },
  "CapacityProfile[TotalSteps]": { name: "TotalSteps", displayName: "Total steps", format: "#,##0" },
  "CapacityProfile[CoveredByLinkedMapping]": { name: "CoveredByLinkedMapping", displayName: "Linked mapping" },
  "[Profile Rows]": { name: "ProfileRows", displayName: "Rows", format: "#,##0" },
};
