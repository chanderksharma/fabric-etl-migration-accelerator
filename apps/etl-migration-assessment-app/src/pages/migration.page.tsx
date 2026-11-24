import { MetricCards, SemanticChart } from "@/components/semantic-visuals";
import { DataState, Panel, Pill, SimpleTable } from "@/components/assessment-ui";
import { useQueryRecords } from "@/hooks/use-query-records";
import { waveDefinitions, waveLabel } from "@/lib/migration-wave";
import { downloadCsv } from "@/lib/download";
import { PageFrame } from "@/pages/portfolio.page";
import { portfolio, workflows } from "@/queries";

export function MigrationPage() {
  const workflowQuery = useQueryRecords(workflows.register);
  const waveTotals = workflowQuery.records.reduce<Record<string, { count: number; effort: number }>>((totals, record) => {
    const label = waveLabel(record.MigrationWave);
    const current = totals[label] ?? { count: 0, effort: 0 };
    totals[label] = {
      count: current.count + 1,
      effort: current.effort + (Number(record.EstimatedEffortDays ?? 0) || 0),
    };
    return totals;
  }, {});

  return (
    <PageFrame
      title="Migration plan"
      subtitle="Sequence work from compiler routing, complexity, and Wave 1 through Wave 4 delivery stages."
    >
      <div className="flex justify-end">
        <button
          type="button"
          className="rounded-lg border bg-background px-3 py-2 text-200 font-semibold hover:bg-hover"
          disabled={!workflowQuery.records.length}
          onClick={() => downloadCsv(
            "migration-plan.csv",
            [
              "WorkflowPath",
              "ComplexityBand",
              "RecommendedTarget",
              "EstimatedEffortDays",
              "MigrationWave",
              "RecommendationReason",
            ],
            workflowQuery.records,
          )}
        >
          Export migration plan
        </button>
      </div>
      <MetricCards
        definition={portfolio.summary}
        metrics={[
          { rawName: "[Wave 1 Assets]", title: "Wave 1", subtitle: "Foundation & prerequisites" },
          { rawName: "[Wave 2 Assets]", title: "Wave 2", subtitle: "Controlled pilot" },
          { rawName: "[Wave 3 Assets]", title: "Wave 3", subtitle: "Medium-complexity scale-out" },
          { rawName: "[Wave 4 Assets]", title: "Wave 4", subtitle: "Manual engineering redesign" },
        ]}
      />
      <div className="grid gap-(--grid-gap) xl:grid-cols-2">
        <SemanticChart
          definition={portfolio.waveDistribution}
          title="Migration wave mix"
          subtitle="Asset allocation across Wave 1 through Wave 4"
        />
        <SemanticChart
          definition={portfolio.targetDistribution}
          title="Implementation backlog"
          subtitle="Recommended Microsoft Fabric targets"
        />
      </div>
      <Panel title="Evidence-based delivery sequence" subtitle="Wave allocations normalized to Wave 1 through Wave 4">
        <DataState isLoading={workflowQuery.isLoading} error={workflowQuery.error} empty={!workflowQuery.records.length} />
        {!!workflowQuery.records.length && (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {waveDefinitions.map((wave, index) => {
              const summary = waveTotals[wave.label] ?? { count: 0, effort: 0 };
              return (
                <div key={wave.label} className="rounded-lg border p-4">
                  <div className="flex items-center justify-between"><Pill>{index + 1}</Pill><strong>{summary.count} workflows</strong></div>
                  <h3 className="mt-3 font-semibold">{wave.label}</h3>
                  <p className="mt-1 text-200 font-semibold text-brand-foreground">{summary.effort.toFixed(1)}d remaining effort</p>
                  <p className="mt-1 text-200 text-muted-foreground">{wave.guidance}</p>
                </div>
              );
            })}
          </div>
        )}
      </Panel>
      <div className="grid gap-(--grid-gap) xl:grid-cols-2">
        <Panel title="Planning basis and assumptions">
          <ul className="space-y-2 text-200 text-muted-foreground">
            <li>Sequencing uses technical complexity, target routing, dependencies, and static findings.</li>
            <li>Business criticality, runtime, schedules, and production failure history are not included.</li>
            <li>Remaining effort (days) is a deterministic baseline from bindings and redesign complexity, not a measured delivery quote.</li>
          </ul>
        </Panel>
        <Panel title="Exit gates" subtitle="Evidence required before promotion">
          <ul className="space-y-2 text-200 text-muted-foreground">
            <li>Connections, identities, and source bindings tested</li>
            <li>Functional parity and owner acceptance recorded</li>
            <li>Deployment, monitoring, restart, and rollback proven</li>
            <li>Representative performance and capacity validated</li>
          </ul>
        </Panel>
      </div>
      <Panel title="Migration backlog and sequencing rationale" subtitle="Open a workflow from the Workflows page for supporting evidence">
        <SimpleTable
          records={workflowQuery.records}
          columns={[
            { key: "WorkflowPath", label: "Workflow" },
            { key: "ComplexityBand", label: "Complexity" },
            { key: "RecommendedTarget", label: "Fabric target" },
            { key: "EstimatedEffortDays", label: "Remaining effort" },
            { key: "MigrationWave", label: "Wave", render: (record) => waveLabel(record.MigrationWave) },
            { key: "RecommendationReason", label: "Rationale" },
          ]}
        />
      </Panel>
    </PageFrame>
  );
}
