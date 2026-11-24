import { describe, expect, it } from "vitest";

import { estimateCapacity } from "@/lib/capacity-estimate";

describe("estimateCapacity", () => {
  it("returns ordered scenario recommendations and workflow contributions in fallback mode", () => {
    const result = estimateCapacity([
      {
        workflowPath: "simple.yxmd",
        recommendedTarget: "Dataflow Gen2",
        toolCount: 5,
        complexityScore: 9,
      },
      {
        workflowPath: "mixed.yxmd",
        recommendedTarget: "Mixed Fabric solution",
        toolCount: 32,
        complexityScore: 81,
      },
    ]);

    expect(result.workflows).toHaveLength(2);
    expect(result.monthlyCuHours).toBeGreaterThan(0);
    expect(result.scenarios.map((item) => item.name)).toEqual([
      "Optimized",
      "Balance",
      "Peak",
    ]);
    expect(result.scenarios[0].requiredCu).toBeLessThanOrEqual(result.scenarios[1].requiredCu);
    expect(result.scenarios[1].requiredCu).toBeLessThanOrEqual(result.scenarios[2].requiredCu);
  });

  it("uses persisted static capacity profiles and supports autoscale Spark offloading", () => {
    const workflows = [
      {
        workflowPath: "orders.yxmd",
        recommendedTarget: "Dataflow Gen2",
        toolCount: 5,
        complexityScore: 9,
        profile: {
          profileKind: "alteryx",
          targetComponents: "Dataflow Gen2",
          complexityUnits: 2.0,
          destCount: 1,
          heavySteps: 0,
          notebookSteps: 0,
          pipelineSteps: 0,
          totalSteps: 5,
          coveredByLinkedMapping: false,
        },
      },
      {
        workflowPath: "joins.yxmd",
        recommendedTarget: "Fabric Notebook",
        toolCount: 13,
        complexityScore: 25,
        profile: {
          profileKind: "alteryx",
          targetComponents: "Fabric Notebook",
          complexityUnits: 6.5,
          destCount: 1,
          heavySteps: 2,
          notebookSteps: 1,
          pipelineSteps: 0,
          totalSteps: 13,
          coveredByLinkedMapping: false,
        },
      },
    ];

    const capacityBilled = estimateCapacity(workflows, { sparkBillingMode: "capacity" });
    const autoscaleBilled = estimateCapacity(workflows, { sparkBillingMode: "autoscale" });

    expect(capacityBilled.calibratedCount).toBe(1);
    expect(capacityBilled.heuristicCount).toBe(1);
    expect(capacityBilled.workflows[0].basis).toBe("calibrated");
    expect(capacityBilled.workflows[1].basis).toBe("heuristic");
    expect(capacityBilled.autoscaleSparkMonthlyCuHours).toBe(0);
    expect(autoscaleBilled.autoscaleSparkMonthlyCuHours).toBeGreaterThan(0);
    expect(autoscaleBilled.monthlyCuHours).toBeLessThan(capacityBilled.monthlyCuHours);
  });

  it("applies per-workflow operational overrides independently", () => {
    const baseline = estimateCapacity([
      {
        workflowPath: "daily.yxmd",
        recommendedTarget: "Dataflow Gen2",
        toolCount: 5,
        complexityScore: 9,
      },
      {
        workflowPath: "hourly.yxmd",
        recommendedTarget: "Dataflow Gen2",
        toolCount: 5,
        complexityScore: 9,
        refreshIntervalMinutes: 60,
        sourceRowsPerRun: 50_000,
        sparkVcores: 16,
      },
    ]);

    expect(baseline.workflows[0].refreshIntervalMinutes).toBe(1440);
    expect(baseline.workflows[1].refreshIntervalMinutes).toBe(60);
    expect(baseline.workflows[1].sourceRowsPerRun).toBe(50_000);
    expect(baseline.workflows[1].sparkVcores).toBe(16);
    expect(baseline.workflows[1].monthlyCuHours)
      .toBeGreaterThan(baseline.workflows[0].monthlyCuHours);
  });

  it("excludes mapping tasks covered by linked mappings and honors notebook runtime overrides", () => {
    const result = estimateCapacity([
      {
        workflowPath: "mt_orders",
        recommendedTarget: "Dataflow Gen2",
        toolCount: 4,
        complexityScore: 8,
        profile: {
          profileKind: "informatica",
          targetComponents: "Dataflow Gen2",
          complexityUnits: 3,
          destCount: 1,
          heavySteps: 1,
          notebookSteps: 0,
          pipelineSteps: 0,
          totalSteps: 4,
          coveredByLinkedMapping: true,
        },
      },
      {
        workflowPath: "nb_scoring.yxmd",
        recommendedTarget: "Fabric Notebook",
        toolCount: 6,
        complexityScore: 15,
        sparkVcores: 8,
        notebookRuntimeSeconds: 300,
        profile: {
          profileKind: "alteryx",
          targetComponents: "Fabric Notebook",
          complexityUnits: 4,
          destCount: 1,
          heavySteps: 0,
          notebookSteps: 2,
          pipelineSteps: 0,
          totalSteps: 6,
          coveredByLinkedMapping: false,
        },
      },
    ]);

    expect(result.excludedCount).toBe(1);
    expect(result.calibratedCount).toBe(0);
    expect(result.heuristicCount).toBe(1);
    expect(result.workflows[0].excluded).toBe(true);
    expect(result.workflows[0].cuSecondsPerRun).toBe(0);
    expect(result.workflows[0].monthlyCuHours).toBe(0);
    expect(result.workflows[1].excluded).toBe(false);
    expect(result.workflows[1].effectiveNotebookRuntimeSeconds).toBe(300);
    // 8 vCores = 4 Spark CU * 300s = 1200 notebook CU-s/run
    expect(result.workflows[1].notebookCuSecondsPerRun).toBe(1200);
  });
});
