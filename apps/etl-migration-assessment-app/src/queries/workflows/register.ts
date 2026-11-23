import type { ColumnMetadataMap } from "@/lib/to-data-table";
import query from "./register.dax?raw";

export const connection = "assessmentmodel";

export { query };

export const columnMetadata: ColumnMetadataMap = {
  "WorkflowAssessment[WorkflowKey]": { name: "WorkflowKey", displayName: "Workflow key" },
  "WorkflowAssessment[WorkflowPath]": { name: "WorkflowPath", displayName: "Workflow" },
  "WorkflowAssessment[SourcePlatform]": { name: "SourcePlatform", displayName: "Source" },
  "WorkflowAssessment[AssetType]": { name: "AssetType", displayName: "Asset type" },
  "WorkflowAssessment[NativeId]": { name: "NativeId", displayName: "Native ID" },
  "WorkflowAssessment[Folder]": { name: "Folder", displayName: "Folder" },
  "WorkflowAssessment[ToolCount]": { name: "ToolCount", displayName: "Tools", format: "#,##0" },
  "WorkflowAssessment[ConnectionCount]": { name: "ConnectionCount", displayName: "Connections", format: "#,##0" },
  "WorkflowAssessment[ComplexityScore]": { name: "ComplexityScore", displayName: "Complexity score", format: "#,##0" },
  "WorkflowAssessment[ComplexityBand]": { name: "ComplexityBand", displayName: "Complexity" },
  "WorkflowAssessment[RecommendedTarget]": { name: "RecommendedTarget", displayName: "Fabric target" },
  "WorkflowAssessment[MigrationWave]": { name: "MigrationWave", displayName: "Migration wave" },
  "WorkflowAssessment[RecommendationReason]": { name: "RecommendationReason", displayName: "Recommendation" },
  "WorkflowAssessment[EstimatedEffortDays]": { name: "EstimatedEffortDays", displayName: "Remaining effort", format: "#,##0.0" },
  "WorkflowAssessment[RegistryVersion]": { name: "RegistryVersion", displayName: "Registry version" },
  "[Assets]": { name: "Assets", displayName: "Assets", format: "#,##0" },
};
