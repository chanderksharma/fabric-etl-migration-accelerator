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
});
