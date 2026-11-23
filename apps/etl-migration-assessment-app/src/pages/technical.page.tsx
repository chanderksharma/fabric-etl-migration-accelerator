import { useMemo, useState } from "react";

import { DataState, Panel, SimpleTable, type TableColumn } from "@/components/assessment-ui";
import { MetricCards, SemanticChart } from "@/components/semantic-visuals";
import { useQueryRecords, type QueryRecord } from "@/hooks/use-query-records";
import { PageFrame } from "@/pages/portfolio.page";
import { downloadCsv } from "@/lib/download";
import { portfolio, technical, workflows } from "@/queries";

type EvidenceTab = "tools" | "findings" | "dependencies" | "nodes" | "connections";

export function TechnicalPage() {
  const [tab, setTab] = useState<EvidenceTab>("tools");
  const [search, setSearch] = useState("");
  const tools = useQueryRecords(technical.tools);
  const findings = useQueryRecords(technical.findings);
  const dependencies = useQueryRecords(technical.dependencies);
  const nodes = useQueryRecords(workflows.nodes);
  const connections = useQueryRecords(workflows.connections);
  const workflowRegister = useQueryRecords(workflows.register);
  const definitions = {
    tools: { result: tools, columns: [{ key: "WorkflowPath", label: "Workflow" }, { key: "ToolName", label: "Tool" }, { key: "SupportCategory", label: "Support category" }, { key: "ToolCount", label: "Count" }] },
    findings: { result: findings, columns: [{ key: "WorkflowPath", label: "Workflow" }, { key: "FindingType", label: "Finding type" }, { key: "FindingText", label: "Evidence" }, { key: "FindingCount", label: "Count" }] },
    dependencies: { result: dependencies, columns: [{ key: "WorkflowPath", label: "Workflow" }, { key: "DependencyReference", label: "Dependency" }, { key: "DependencyCount", label: "Count" }] },
    nodes: { result: nodes, columns: [{ key: "WorkflowPath", label: "Workflow" }, { key: "NodeId", label: "Node ID" }, { key: "NodeName", label: "Tool" }, { key: "NodeLabel", label: "Label" }, { key: "SupportCategory", label: "Support" }, { key: "Disabled", label: "Disabled" }] },
    connections: { result: connections, columns: [{ key: "WorkflowPath", label: "Workflow" }, { key: "SourceNodeId", label: "Source" }, { key: "SourceAnchor", label: "Anchor" }, { key: "TargetNodeId", label: "Target" }, { key: "TargetAnchor", label: "Anchor" }] },
  } satisfies Record<EvidenceTab, { result: ReturnType<typeof useQueryRecords>; columns: TableColumn[] }>;
  const active = definitions[tab];
  const pathByKey = useMemo(() => new Map(
    workflowRegister.records.map((record) => [record.WorkflowKey, record.WorkflowPath]),
  ), [workflowRegister.records]);
  const activeRecords = useMemo(() => active.result.records.map((record) => ({
    ...record,
    WorkflowPath: record.WorkflowPath || pathByKey.get(record.WorkflowKey),
  })), [active.result.records, pathByKey]);
  const filtered = useMemo(() => activeRecords.filter((record) =>
    Object.values(record).some((value) => String(value ?? "").toLowerCase().includes(search.toLowerCase())),
  ), [activeRecords, search]);

  return (
    <PageFrame
      title="Technical evidence"
      subtitle="Inspect parsed components, mappings, dependencies, findings, and source connections."
    >
      <MetricCards
        definition={portfolio.summary}
        metrics={[
          { rawName: "[Source Components]", title: "Source components", subtitle: "Parsed workflow nodes" },
          { rawName: "[Connections]", title: "Connections", subtitle: "Bounded source edges" },
          { rawName: "[Dependencies]", title: "Dependencies", subtitle: "External references" },
          { rawName: "[Static Findings]", title: "Static findings", subtitle: "Deterministic evidence" },
        ]}
      />
      <div className="grid gap-(--grid-gap) xl:grid-cols-3">
        <SemanticChart definition={technical.supportDistribution} title="Tool mappings" subtitle="Source components by support category" />
        <Panel title="Assessment scope and coverage" className="xl:col-span-2">
          <p className="text-300 text-muted-foreground">Parser and registry versions are retained by workflow. Unknown mappings remain explicit redesign requirements. Static evidence does not establish semantic parity, connector availability, credential safety, runtime performance, or production readiness.</p>
        </Panel>
      </div>
      <Panel title="Technical assessment registers" subtitle="Bounded normalized evidence from the latest completed run">
        <div className="mb-4 flex justify-end">
          <button
            type="button"
            className="rounded-lg border bg-background px-3 py-2 text-200 font-semibold hover:bg-hover"
            disabled={!filtered.length}
            onClick={() => downloadCsv(
              `technical-${tab}.csv`,
              active.columns.map((column) => column.key),
              filtered,
            )}
          >
            Export current register
          </button>
        </div>
        <div className="mb-4 flex flex-wrap gap-2" role="tablist" aria-label="Technical evidence registers">
          {(Object.keys(definitions) as EvidenceTab[]).map((key) => <button key={key} type="button" role="tab" aria-selected={tab === key} className={`rounded-lg px-3 py-2 text-200 font-semibold capitalize ${tab === key ? "bg-brand text-on-brand" : "border hover:bg-hover"}`} onClick={() => setTab(key)}>{key}</button>)}
        </div>
        <input className="mb-4 w-full rounded-lg border bg-background p-3" placeholder="Search technical evidence" value={search} onChange={(event) => setSearch(event.target.value)} />
        <DataState isLoading={active.result.isLoading} error={active.result.error} empty={!filtered.length} />
        {!!filtered.length && <SimpleTable records={filtered.slice(0, 250) as QueryRecord[]} columns={active.columns} />}
        {filtered.length > 250 && <p className="mt-3 text-200 text-muted-foreground">Showing the first 250 of {filtered.length} matching records.</p>}
      </Panel>
    </PageFrame>
  );
}
