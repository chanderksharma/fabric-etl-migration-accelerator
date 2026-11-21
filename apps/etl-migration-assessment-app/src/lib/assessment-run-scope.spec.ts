import { describe, expect, it } from "vitest";

import {
  isAssessmentRunId,
  scopeAssessmentRunQuery,
} from "@/lib/assessment-run-scope";

describe("assessment run query scope", () => {
  const runId = "8f50f18a-ae85-4be6-9224-35f4f4ce526b";
  const latestFilter = "'AssessmentRun'[IsLatestCompletedRun] = TRUE()";

  it("keeps latest-run queries unchanged when no historical run is selected", () => {
    const query = `EVALUATE CALCULATETABLE(ROW("Count", 1), ${latestFilter})`;

    expect(scopeAssessmentRunQuery(query, null)).toBe(query);
  });

  it("replaces every latest-run predicate with the selected immutable run ID", () => {
    const query = `${latestFilter}\n${latestFilter}`;
    const scoped = scopeAssessmentRunQuery(query, runId);

    expect(scoped).not.toContain(latestFilter);
    expect(scoped.match(new RegExp(runId, "g"))).toHaveLength(2);
  });

  it("rejects unsafe run IDs before building DAX", () => {
    expect(isAssessmentRunId('bad" OR TRUE()')).toBe(false);
    expect(() => scopeAssessmentRunQuery(latestFilter, 'bad" OR TRUE()')).toThrow(
      "Invalid assessment run ID",
    );
  });
});
