import type { VisualizationSpec } from "@microsoft/fabric-visuals";
import type { ColumnMetadataMap } from "@/lib/to-data-table";
import query from "./wave-distribution.dax?raw";

export const connection = "assessmentmodel";

export { query };

export const columnMetadata: ColumnMetadataMap = {
  "WorkflowAssessment[MigrationWave]": { name: "MigrationWave", displayName: "Migration wave" },
  "[Assets]": { name: "Assets", displayName: "Assets", format: "#,##0" },
};

export const vegaLiteSpec: VisualizationSpec = {
  $schema: "https://vega.github.io/schema/vega-lite/v6.json",
  mark: { type: "bar", cornerRadiusTopLeft: 4, cornerRadiusTopRight: 4 },
  encoding: {
    x: {
      field: "MigrationWave",
      type: "nominal",
      sort: ["Wave 1", "Wave 2", "Pilot", "Redesign"],
      title: null,
    },
    y: { field: "Assets", type: "quantitative", title: "Assets" },
    color: { field: "MigrationWave", type: "nominal", legend: null },
    tooltip: [
      { field: "MigrationWave", type: "nominal", title: "Migration wave" },
      { field: "Assets", type: "quantitative", title: "Assets", format: ",.0f" },
    ],
  },
};

export function createWaveDistribution() {
  return { connection, query, columnMetadata, vegaLiteSpec };
}
