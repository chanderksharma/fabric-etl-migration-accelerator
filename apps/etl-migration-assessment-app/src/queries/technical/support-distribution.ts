import type { VisualizationSpec } from "@microsoft/fabric-visuals";
import type { ColumnMetadataMap } from "@/lib/to-data-table";
import query from "./support-distribution.dax?raw";

export const connection = "assessmentmodel";

export { query };

export const columnMetadata: ColumnMetadataMap = {
  "ToolInventory[SupportCategory]": { name: "SupportCategory", displayName: "Support category" },
  "[Tool Count]": { name: "ToolCount", displayName: "Tools", format: "#,##0" },
};

export const vegaLiteSpec: VisualizationSpec = {
  $schema: "https://vega.github.io/schema/vega-lite/v6.json",
  mark: { type: "bar", cornerRadiusEnd: 4 },
  encoding: {
    y: { field: "SupportCategory", type: "nominal", sort: "-x", title: null },
    x: { field: "ToolCount", type: "quantitative", title: "Tools" },
    color: {
      field: "SupportCategory",
      type: "nominal",
      legend: null,
      scale: { range: ["#107c10", "#0078d4", "#ffb900", "#d13438"] },
    },
    tooltip: [
      { field: "SupportCategory", type: "nominal", title: "Support category" },
      { field: "ToolCount", type: "quantitative", title: "Tools", format: ",.0f" },
    ],
  },
};

export function createSupportDistribution() {
  return { connection, query, columnMetadata, vegaLiteSpec };
}
