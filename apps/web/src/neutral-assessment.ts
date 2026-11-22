export type NeutralComponent = {
  operation: string;
  count: number;
  classification: string;
};

type NeutralAsset = {
  path: string;
  name: string;
  source_platform: string;
  source_product: string;
  component_count: number;
  connection_count: number;
  complexity_score: number;
  complexity_band: string;
  intrinsic_effort_days: number;
  unknown_components: string[];
  inventory?: NeutralComponent[];
  dependencies?: string[];
  data_sources?: string[];
};

export type NeutralAssessment = {
  workflow_count: number;
  failed_count: number;
  assessments: NeutralAsset[];
  failures: string[];
};

export function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(item => typeof item === "string");
}

export function parseNeutralAssessment(value: unknown): NeutralAssessment {
  if (typeof value !== "object" || value === null) throw new Error("Invalid neutral assessment");
  const result = value as Record<string, unknown>;
  if (
    typeof result.workflow_count !== "number" || typeof result.failed_count !== "number" ||
    !isStringArray(result.failures) || !Array.isArray(result.assessments) ||
    !result.assessments.every((item: unknown) => {
      if (typeof item !== "object" || item === null) return false;
      const asset = item as Record<string, unknown>;
      return typeof asset.path === "string" && typeof asset.name === "string" &&
        typeof asset.source_platform === "string" && typeof asset.source_product === "string" &&
        typeof asset.component_count === "number" && typeof asset.connection_count === "number" &&
        typeof asset.complexity_score === "number" && typeof asset.complexity_band === "string" &&
        typeof asset.intrinsic_effort_days === "number" && isStringArray(asset.unknown_components);
    })
  ) throw new Error("Invalid neutral assessment");
  return value as NeutralAssessment;
}
