import { MetricCards, SemanticChart } from "@/components/semantic-visuals";
import { DataState, Panel, Pill, SimpleTable } from "@/components/assessment-ui";
import { useQueryRecords } from "@/hooks/use-query-records";
import { PageFrame } from "@/pages/portfolio.page";
import { portfolio, workflows } from "@/queries";

export function MigrationPage() {
  const workflowQuery = useQueryRecords(workflows.register);
  const waveGroups = Object.entries(
    workflowQuery.records.reduce<Record<string, typeof workflowQuery.records>>((groups, record) => {
      const wave = String(record.MigrationWave || "Unassigned");
      (groups[wave] ??= []).push(record);
      return groups;
    }, {}),
  ).sort(([left], [right]) => left.localeCompare(right));

  return (
    <PageFrame
      title="Migration plan"
      subtitle="Sequence work from compiler routing, complexity, and migration-wave evidence."
    >
      <MetricCards
        definition={portfolio.summary}
        metrics={[
          { rawName: "[Pilot Assets]", title: "Pilot", subtitle: "Validate implementation patterns" },
          { rawName: "[Redesign Assets]", title: "Redesign", subtitle: "Requires engineering changes" },
          { rawName: "[Manual Review Assets]", title: "Manual review", subtitle: "Unsupported or ambiguous" },
          { rawName: "[Average Complexity Score]", title: "Average complexity", subtitle: "Portfolio technical score" },
        ]}
      />
      <div className="grid gap-(--grid-gap) xl:grid-cols-2">
        <SemanticChart
          definition={portfolio.waveDistribution}
          title="Migration wave mix"
          subtitle="Asset allocation across the delivery sequence"
        />
        <SemanticChart
          definition={portfolio.targetDistribution}
          title="Implementation backlog"
          subtitle="Recommended Microsoft Fabric targets"
        />
      </div>
      <Panel title="Evidence-based delivery sequence" subtitle="Wave allocations from the latest completed assessment">
        <DataState isLoading={workflowQuery.isLoading} error={workflowQuery.error} empty={!workflowQuery.records.length} />
        {!!waveGroups.length && (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {waveGroups.map(([wave, records], index) => (
              <div key={wave} className="rounded-lg border p-4">
                <div className="flex items-center justify-between"><Pill>{index + 1}</Pill><strong>{records.length} workflows</strong></div>
                <h3 className="mt-3 font-semibold">{wave}</h3>
                <p className="mt-1 text-200 text-muted-foreground">{waveGuidance(wave)}</p>
              </div>
            ))}
          </div>
        )}
      </Panel>
      <div className="grid gap-(--grid-gap) xl:grid-cols-2">
        <Panel title="Planning basis and assumptions">
          <ul className="space-y-2 text-200 text-muted-foreground">
            <li>Sequencing uses technical complexity, target routing, dependencies, and static findings.</li>
            <li>Business criticality, runtime, schedules, and production failure history are not included.</li>
            <li>Delivery effort is not persisted in the normalized semantic model and is not inferred here.</li>
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
            { key: "MigrationWave", label: "Wave" },
            { key: "RecommendationReason", label: "Rationale" },
          ]}
        />
      </Panel>
    </PageFrame>
  );
}

function waveGuidance(wave: string): string {
  const value = wave.toLowerCase();
  if (value.includes("pilot")) return "Prove representative transformations and operational controls.";
  if (value.includes("redesign")) return "Resolve unsupported or specialist workflow semantics.";
  if (value.includes("1")) return "Resolve shared prerequisites and agree source bindings.";
  return "Apply reviewed patterns with measured exit evidence.";
}
