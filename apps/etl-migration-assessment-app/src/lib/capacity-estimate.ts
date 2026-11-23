export type SparkBillingMode = "capacity" | "autoscale";

export interface CapacityProfileMetrics {
  profileKind: string;
  targetComponents: string;
  complexityUnits: number;
  destCount: number;
  heavySteps: number;
  notebookSteps: number;
  pipelineSteps: number;
  totalSteps: number;
  coveredByLinkedMapping: boolean;
}

export interface CapacityWorkflow {
  workflowPath: string;
  recommendedTarget: string;
  toolCount: number;
  complexityScore: number;
  profile?: CapacityProfileMetrics;
  refreshIntervalMinutes?: number;
  sourceRowsPerRun?: number;
  sparkVcores?: number;
}

export interface CapacitySettings {
  refreshIntervalMinutes: number;
  sourceRowsPerRun: number;
  sparkVcores: number;
  daysPerMonth: number;
  targetUtilization: number;
  burstWindowMinutes: number;
  sparkBillingMode: SparkBillingMode;
  interactiveUsers: number;
}

export const defaultCapacitySettings: CapacitySettings = {
  refreshIntervalMinutes: 1440,
  sourceRowsPerRun: 1000,
  sparkVcores: 8,
  daysPerMonth: 31,
  targetUtilization: 0.8,
  burstWindowMinutes: 5,
  sparkBillingMode: "capacity",
  interactiveUsers: 1,
};

export interface CapacityWorkflowEstimate extends CapacityWorkflow {
  basis: "calibrated" | "heuristic" | "normalized heuristic";
  dataflowCuSecondsPerRun: number;
  notebookCuSecondsPerRun: number;
  pipelineCuSecondsPerRun: number;
  cuSecondsPerRun: number;
  monthlyCuHours: number;
  autoscaleSparkMonthlyCuHours: number;
}

export interface CapacityScenario {
  name: "Optimized" | "Balance" | "Peak";
  requiredCu: number;
  recommendedSku: string;
}

export interface CapacityEstimate {
  monthlyCuHours: number;
  autoscaleSparkMonthlyCuHours: number;
  calibratedCount: number;
  heuristicCount: number;
  scenarios: CapacityScenario[];
  workflows: CapacityWorkflowEstimate[];
}

const skuTiers = [2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192];
const fabricComponents = new Set(["Dataflow Gen2", "Fabric Notebook", "Fabric Pipeline"]);

// Constants synchronized with src/accelerator/capacity.py (CAPACITY_MODEL_VERSION = "3.1.0").
const MODEL = {
  secondsPerComplexityElement: 5.231236918751955,
  minimumSecondsPerOutput: 39.18196452145214,
  initialCuRate: 12,
  subsequentCuRate: 1.5,
  cuRateThresholdSeconds: 600,
  extraOutputOverlap: 0,
  projectionVariation: 0.01,
  secondsPerHeavyStepPerThousandRows: 1.255806863185154,
  secondsPerHundredRows: 0.000189,
  calibrationMultiplier: 1,
  pipelineOrchestrationCuSecondsPerActivity: 20,
  pipelineCopyBaseSeconds: 15,
  pipelineCopyCuPerSecond: 1.5,
  activeUsersPerDay: 1,
  averageActiveHoursPerUser: 2,
  peakConcurrentUsers: 1,
  cuPerActiveUser: 0.3,
  interactivePeakFactor: 2,
  balanceWeight: 0.5,
};

export function estimateCapacity(
  workflows: CapacityWorkflow[],
  settingsInput: Partial<CapacitySettings> = {},
): CapacityEstimate {
  const settings: CapacitySettings = {
    ...defaultCapacitySettings,
    ...settingsInput,
    refreshIntervalMinutes: clampPositive(
      settingsInput.refreshIntervalMinutes ?? defaultCapacitySettings.refreshIntervalMinutes,
      1440,
      1,
      1440,
    ),
    sourceRowsPerRun: clampPositive(
      settingsInput.sourceRowsPerRun ?? defaultCapacitySettings.sourceRowsPerRun,
      1000,
      1,
      100_000_000,
    ),
    sparkVcores: clampPositive(
      settingsInput.sparkVcores ?? defaultCapacitySettings.sparkVcores,
      8,
      2,
      512,
    ),
    daysPerMonth: clampPositive(
      settingsInput.daysPerMonth ?? defaultCapacitySettings.daysPerMonth,
      31,
      1,
      366,
    ),
    targetUtilization: clampPositive(
      settingsInput.targetUtilization ?? defaultCapacitySettings.targetUtilization,
      0.8,
      0.1,
      1,
    ),
    burstWindowMinutes: clampPositive(
      settingsInput.burstWindowMinutes ?? defaultCapacitySettings.burstWindowMinutes,
      5,
      1,
      1440,
    ),
    interactiveUsers: clampPositive(
      settingsInput.interactiveUsers ?? defaultCapacitySettings.interactiveUsers,
      1,
      0,
      10_000,
    ),
  };

  const estimates = workflows.map((workflow) => estimateWorkflow(workflow, settings));
  const dailyCuSeconds = estimates.reduce(
    (total, item) =>
      total + item.cuSecondsPerRun * 1440 / (item.refreshIntervalMinutes ?? settings.refreshIntervalMinutes),
    0,
  );
  const monthlyCuHours = estimates.reduce((total, item) => total + item.monthlyCuHours, 0);
  const autoscaleSparkMonthlyCuHours = estimates.reduce(
    (total, item) => total + item.autoscaleSparkMonthlyCuHours,
    0,
  );
  const largestRun = Math.max(0, ...estimates.map((item) => item.cuSecondsPerRun));
  const peakWindowCuSeconds = estimates.reduce(
    (total, item) => {
      const runsPerDay = 1440 / (item.refreshIntervalMinutes ?? settings.refreshIntervalMinutes);
      const burstFactor = Math.max(settings.burstWindowMinutes * runsPerDay / 1440, 1);
      return total + item.cuSecondsPerRun * burstFactor;
    },
    0,
  );

  const backgroundCu = dailyCuSeconds / 86_400;
  const interactiveAverage =
    settings.interactiveUsers *
    MODEL.averageActiveHoursPerUser *
    3600 *
    MODEL.cuPerActiveUser /
    86_400;
  const interactivePeak =
    settings.interactiveUsers * MODEL.cuPerActiveUser * MODEL.interactivePeakFactor;
  const averageNeed = (backgroundCu + interactiveAverage) / settings.targetUtilization;
  const windowSeconds = settings.burstWindowMinutes * 60;
  const optimized = Math.max(averageNeed, largestRun / windowSeconds + interactivePeak);
  const peak = Math.max(averageNeed, peakWindowCuSeconds / windowSeconds + interactivePeak);
  const balance = optimized + (peak - optimized) * MODEL.balanceWeight;

  return {
    monthlyCuHours,
    autoscaleSparkMonthlyCuHours,
    calibratedCount: estimates.filter((item) => item.basis === "calibrated").length,
    heuristicCount: estimates.filter((item) => item.basis !== "calibrated").length,
    workflows: estimates,
    scenarios: [
      scenario("Optimized", optimized),
      scenario("Balance", balance),
      scenario("Peak", peak),
    ],
  };
}

function estimateWorkflow(
  workflow: CapacityWorkflow,
  settings: CapacitySettings,
): CapacityWorkflowEstimate {
  const workflowSettings = {
    ...settings,
    refreshIntervalMinutes: clampPositive(
      workflow.refreshIntervalMinutes ?? settings.refreshIntervalMinutes,
      settings.refreshIntervalMinutes,
      1,
      1440,
    ),
    sourceRowsPerRun: clampPositive(
      workflow.sourceRowsPerRun ?? settings.sourceRowsPerRun,
      settings.sourceRowsPerRun,
      1,
      100_000_000,
    ),
    sparkVcores: clampPositive(
      workflow.sparkVcores ?? settings.sparkVcores,
      settings.sparkVcores,
      2,
      512,
    ),
  };
  const runsPerDay = 1440 / workflowSettings.refreshIntervalMinutes;
  if (!workflow.profile) {
    return estimateNormalizedFallback(workflow, workflowSettings, runsPerDay);
  }

  const profile = workflow.profile;
  const components = resolveComponents(workflow.recommendedTarget, profile.targetComponents);
  const hasDataflow = components.includes("Dataflow Gen2");
  const hasNotebook = components.includes("Fabric Notebook");
  const hasPipeline = components.includes("Fabric Pipeline");
  const basis: CapacityWorkflowEstimate["basis"] =
    workflow.recommendedTarget === "Dataflow Gen2" &&
    components.length === 1 &&
    components[0] === "Dataflow Gen2"
      ? "calibrated"
      : "heuristic";

  let dataflowCuSeconds = 0;
  if (hasDataflow) {
    const complexitySeconds = profile.complexityUnits * MODEL.secondsPerComplexityElement;
    const volumeSeconds = (workflowSettings.sourceRowsPerRun / 100) * MODEL.secondsPerHundredRows;
    const baseSeconds = Math.max(
      MODEL.minimumSecondsPerOutput,
      complexitySeconds,
      volumeSeconds,
    );
    const querySeconds =
      baseSeconds +
      (workflowSettings.sourceRowsPerRun / 1000) *
        profile.heavySteps *
        MODEL.secondsPerHeavyStepPerThousandRows;
    const outputs = Math.max(profile.destCount, 1);
    const overlap = 1 + (outputs - 1) * MODEL.extraOutputOverlap;
    dataflowCuSeconds =
      overlap *
      (Math.min(querySeconds, MODEL.cuRateThresholdSeconds) * MODEL.initialCuRate +
        Math.max(querySeconds - MODEL.cuRateThresholdSeconds, 0) * MODEL.subsequentCuRate) *
      MODEL.calibrationMultiplier;
  }

  let notebookCuSeconds = 0;
  if (hasNotebook) {
    const sparkCu = workflowSettings.sparkVcores / 2;
    const nbWeight = hasDataflow
      ? Math.max(
          1,
          profile.notebookSteps * 1.5 + Math.max(profile.totalSteps - profile.notebookSteps, 0) * 0.15,
        )
      : Math.max(1, profile.complexityUnits);
    const runtimeSeconds = Math.max(
      60,
      45 +
        nbWeight * 4 +
        (workflowSettings.sourceRowsPerRun / 50_000) * 5 +
        profile.heavySteps * (workflowSettings.sourceRowsPerRun / 1000) * 0.5,
    );
    notebookCuSeconds = sparkCu * runtimeSeconds;
  }

  let pipelineCuSeconds = 0;
  if (hasPipeline) {
    const orchestratedChildren = (hasDataflow ? 1 : 0) + (hasNotebook ? 1 : 0);
    const activityCount = Math.max(orchestratedChildren, 1) + profile.pipelineSteps;
    const orchestrationCu = activityCount * MODEL.pipelineOrchestrationCuSecondsPerActivity;
    const hasCopy = profile.pipelineSteps > 0 || !(hasDataflow || hasNotebook);
    const copySeconds = hasCopy
      ? MODEL.pipelineCopyBaseSeconds + (workflowSettings.sourceRowsPerRun / 100_000) * 10
      : 0;
    pipelineCuSeconds = orchestrationCu + copySeconds * MODEL.pipelineCopyCuPerSecond;
  }

  const autoscale = settings.sparkBillingMode === "autoscale";
  const cuSeconds = autoscale
    ? dataflowCuSeconds + pipelineCuSeconds
    : dataflowCuSeconds + notebookCuSeconds + pipelineCuSeconds;
  const autoscaleCuSeconds = autoscale ? notebookCuSeconds * (1 + MODEL.projectionVariation) : 0;
  const projected = cuSeconds * (1 + MODEL.projectionVariation);

  return {
    ...workflow,
    refreshIntervalMinutes: workflowSettings.refreshIntervalMinutes,
    sourceRowsPerRun: workflowSettings.sourceRowsPerRun,
    sparkVcores: workflowSettings.sparkVcores,
    basis,
    dataflowCuSecondsPerRun: dataflowCuSeconds,
    notebookCuSecondsPerRun: notebookCuSeconds,
    pipelineCuSecondsPerRun: pipelineCuSeconds,
    cuSecondsPerRun: projected,
    monthlyCuHours: projected * runsPerDay * settings.daysPerMonth / 3600,
    autoscaleSparkMonthlyCuHours: autoscaleCuSeconds * runsPerDay * settings.daysPerMonth / 3600,
  };
}

function estimateNormalizedFallback(
  workflow: CapacityWorkflow,
  settings: CapacitySettings,
  runsPerDay: number,
): CapacityWorkflowEstimate {
  const dataflow = Math.max(470.2, workflow.toolCount * 20);
  const notebook = Math.max(240, (180 + workflow.toolCount * 3) * (settings.sparkVcores / 8));
  const pipeline = 40;
  let dataflowCuSeconds = 0;
  let notebookCuSeconds = 0;
  let pipelineCuSeconds = 0;

  if (workflow.recommendedTarget === "Fabric Notebook") {
    notebookCuSeconds = notebook;
  } else if (workflow.recommendedTarget === "Fabric Pipeline") {
    pipelineCuSeconds = pipeline;
  } else if (workflow.recommendedTarget === "Mixed Fabric solution") {
    dataflowCuSeconds = dataflow;
    notebookCuSeconds = notebook;
    pipelineCuSeconds = pipeline;
  } else {
    dataflowCuSeconds = dataflow;
  }

  const autoscale = settings.sparkBillingMode === "autoscale";
  const cuSeconds = autoscale
    ? dataflowCuSeconds + pipelineCuSeconds
    : dataflowCuSeconds + notebookCuSeconds + pipelineCuSeconds;
  const autoscaleCuSeconds = autoscale ? notebookCuSeconds * (1 + MODEL.projectionVariation) : 0;
  const projected = cuSeconds * (1 + MODEL.projectionVariation);

  return {
    ...workflow,
    refreshIntervalMinutes: settings.refreshIntervalMinutes,
    sourceRowsPerRun: settings.sourceRowsPerRun,
    sparkVcores: settings.sparkVcores,
    basis: "normalized heuristic",
    dataflowCuSecondsPerRun: dataflowCuSeconds,
    notebookCuSecondsPerRun: notebookCuSeconds,
    pipelineCuSecondsPerRun: pipelineCuSeconds,
    cuSecondsPerRun: projected,
    monthlyCuHours: projected * runsPerDay * settings.daysPerMonth / 3600,
    autoscaleSparkMonthlyCuHours: autoscaleCuSeconds * runsPerDay * settings.daysPerMonth / 3600,
  };
}

function resolveComponents(recommendedTarget: string, targetComponents: string): string[] {
  const parsed = targetComponents
    .split(",")
    .map((part) => part.trim())
    .filter((part) => fabricComponents.has(part));
  if (parsed.length > 0) return parsed;
  if (recommendedTarget === "Mixed Fabric solution") {
    return ["Dataflow Gen2", "Fabric Notebook", "Fabric Pipeline"];
  }
  if (fabricComponents.has(recommendedTarget)) {
    return [recommendedTarget];
  }
  return ["Dataflow Gen2"];
}

function clampPositive(value: number, fallback: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return fallback;
  return Math.min(Math.max(value, min), max);
}

function scenario(name: CapacityScenario["name"], requiredCu: number): CapacityScenario {
  return {
    name,
    requiredCu,
    recommendedSku: skuFor(requiredCu),
  };
}

function skuFor(requiredCu: number): string {
  const tier = skuTiers.find((value) => requiredCu <= value);
  return tier ? `F${tier}` : "Multiple capacities";
}
