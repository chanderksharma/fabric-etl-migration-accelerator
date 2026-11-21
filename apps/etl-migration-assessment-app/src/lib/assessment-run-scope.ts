const latestCompletedRunFilter = "'AssessmentRun'[IsLatestCompletedRun] = TRUE()";
const runIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function isAssessmentRunId(value: string): boolean {
  return runIdPattern.test(value);
}

export function scopeAssessmentRunQuery(query: string, runId: string | null): string {
  if (!runId || !query.includes(latestCompletedRunFilter)) {
    return query;
  }
  if (!isAssessmentRunId(runId)) {
    throw new Error("Invalid assessment run ID.");
  }
  return query.replaceAll(
    latestCompletedRunFilter,
    `'AssessmentRun'[RunId] = "${runId}"`,
  );
}
