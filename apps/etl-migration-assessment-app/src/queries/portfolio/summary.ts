import query from "./summary.dax?raw";
import type { ColumnMetadataMap } from "@/lib/to-data-table";

export const connection = "assessmentmodel";

export { query };

export const columnMetadata: ColumnMetadataMap = {
  "[Assessed Assets]": { name: "AssessedAssets", displayName: "Assessed assets", format: "#,##0" },
  "[High Complexity Assets]": { name: "HighComplexityAssets", displayName: "High complexity", format: "#,##0" },
  "[Wave 1 Assets]": { name: "Wave1Assets", displayName: "Wave 1", format: "#,##0" },
  "[Wave 2 Assets]": { name: "Wave2Assets", displayName: "Wave 2", format: "#,##0" },
  "[Wave 3 Assets]": { name: "Wave3Assets", displayName: "Wave 3", format: "#,##0" },
  "[Wave 4 Assets]": { name: "Wave4Assets", displayName: "Wave 4", format: "#,##0" },
  "[Pilot Assets]": { name: "PilotAssets", displayName: "Pilot assets", format: "#,##0" },
  "[Redesign Assets]": { name: "RedesignAssets", displayName: "Redesign assets", format: "#,##0" },
  "[Manual Review Assets]": { name: "ManualReviewAssets", displayName: "Manual review", format: "#,##0" },
  "[Average Complexity Score]": { name: "AverageComplexityScore", displayName: "Average complexity", format: "#,##0.0" },
  "[Source Components]": { name: "SourceComponents", displayName: "Source components", format: "#,##0" },
  "[Connections]": { name: "Connections", displayName: "Connections", format: "#,##0" },
  "[Dependencies]": { name: "Dependencies", displayName: "Dependencies", format: "#,##0" },
  "[Static Findings]": { name: "StaticFindings", displayName: "Static findings", format: "#,##0" },
};
