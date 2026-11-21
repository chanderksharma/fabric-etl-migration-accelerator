import { describe, expect, it } from "vitest";

import { waveDefinitions, waveGuidance, waveLabel } from "@/lib/migration-wave";
import { scopeAssessmentRunQuery } from "@/lib/assessment-run-scope";
import { portfolio } from "@/queries";

describe("migration-wave normalization", () => {
  it("normalizes engine waves to Wave 1 through Wave 4 like the workbench", () => {
    expect(waveDefinitions.map((item) => item.label)).toEqual([
      "Wave 1",
      "Wave 2",
      "Wave 3",
      "Wave 4",
    ]);
    expect(waveLabel("Wave 1")).toBe("Wave 1");
    expect(waveLabel("Pilot")).toBe("Wave 2");
    expect(waveLabel("Wave 2")).toBe("Wave 3");
    expect(waveLabel("Redesign")).toBe("Wave 4");
    expect(waveLabel("")).toBe("Unassigned");
    expect(waveGuidance("Pilot")).toContain("operational controls");
  });

  it("scopes wave-distribution and summary queries cleanly by RunId", () => {
    const runId = "119ed764-0e42-45fa-b57b-194ef2817934";
    const scopedWave = scopeAssessmentRunQuery(portfolio.waveDistribution.query, runId);
    const scopedSummary = scopeAssessmentRunQuery(portfolio.summary.query, runId);
    expect(scopedWave).toContain(`'AssessmentRun'[RunId] = "${runId}"`);
    expect(scopedWave).not.toContain("IsLatestCompletedRun");
    expect(scopedSummary).toContain("[Wave 1 Assets]");
    expect(scopedSummary).toContain("[Wave 4 Assets]");
  });
});
