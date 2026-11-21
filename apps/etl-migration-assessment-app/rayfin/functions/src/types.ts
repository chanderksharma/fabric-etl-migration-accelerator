/**
 * Function schema types for RayfinClient.
 *
 * AUTO-GENERATED — do not edit manually.
 * Re-generated automatically when function source files change.
 *
 * If this file is not updating automatically, run:
 *   rayfin dev functions apply
 *
 * The schema is a closed object type: only the function names listed
 * below are accepted by RayfinClient.functions.<name>.invoke(...).
 * Adding, renaming, or changing the signature of a udf.func() call
 * regenerates this file and surfaces type errors at every consumer.
 *
 * IMPORTANT: This file must NOT import any Node.js packages — it is
 * resolved by the frontend app's TypeScript compiler.
 */

export type AppFunctionsSchema = {
  uploadWorkflow: {
    input: { fileName: string; contentBase64: string; inputFolder: string };
    output: { fileName: string; inputPath: string; size: number };
  };
  getDeploymentConfiguration: {
    input: Record<string, never>;
    output: { githubConfigured: boolean; gitlabConfigured: boolean };
  };
  previewDeployment: {
    input: { providerValue: string; repositoryUrl: string; refValue: string; conflictBehaviorValue: string; selectionsJson: string };
    output: { manifest: { version: 1; provider: 'github' | 'gitlab'; repository: string; ref: string; conflictBehavior: 'Fail' | 'Skip' | 'Update'; selections: { workflowPath: string; artifactPath: string; target: 'notebook' | 'dataflow' | 'pipeline' | 'bundle' }[]; expiresAt: string }; confirmationToken: string };
  };
  dispatchDeployment: {
    input: { confirmationToken: string };
    output: { provider: 'github' | 'gitlab'; repository: string; ref: string; results: { workflowPath: string; artifactPath: string; target: 'notebook' | 'dataflow' | 'pipeline' | 'bundle'; status: 'dispatched' | 'failed'; deploymentId?: undefined | string; runUrl?: undefined | string; error?: undefined | string }[] };
  };
  startAssessment: {
    input: { inputPath: string };
    output: { jobInstanceId: string; statusUrl: string };
  };
  getAssessmentStatus: {
    input: { jobInstanceId: string };
    output: { status: string; startTimeUtc?: undefined | string; endTimeUtc?: undefined | string; exitValue?: undefined | string; failureReason?: unknown };
  };
};
