import { useEffect, useMemo, useState } from "react";
import { ArrowRight, X } from "lucide-react";

import { DataState, Panel, Pill, SimpleTable } from "@/components/assessment-ui";
import { useQueryRecords, type QueryRecord } from "@/hooks/use-query-records";
import { formatValue } from "@/lib/format-value";
import { PageFrame } from "@/pages/portfolio.page";
import { workflows } from "@/queries";

type DetailTab = "summary" | "source" | "design" | "risk" | "validation" | "deployment";

export function WorkflowsPage({
  onOpenDeployment,
}: {
  onOpenDeployment?: (workflowPath: string) => void;
}) {
  const workflowQuery = useQueryRecords(workflows.register);
  const [search, setSearch] = useState("");
  const [complexity, setComplexity] = useState("All");
  const [target, setTarget] = useState("All");
  const [selectedKey, setSelectedKey] = useState<string>();

  const filtered = useMemo(() => workflowQuery.records.filter((record) => {
    const path = String(record.WorkflowPath ?? "");
    return (
      path.toLowerCase().includes(search.toLowerCase()) &&
      (complexity === "All" || record.ComplexityBand === complexity) &&
      (target === "All" || record.RecommendedTarget === target)
    );
  }), [complexity, search, target, workflowQuery.records]);
  const selected = workflowQuery.records.find(
    (record) => String(record.WorkflowKey ?? record.WorkflowPath) === selectedKey,
  );
  const detailKey =
    typeof selected?.WorkflowKey === "string" && /^[0-9a-f]{64}$/i.test(selected.WorkflowKey)
      ? selected.WorkflowKey
      : undefined;
  const nodeQuery = useQueryRecords(useMemo(() => workflows.workflowNodesQuery(detailKey), [detailKey]));
  const connectionQuery = useQueryRecords(useMemo(() => workflows.workflowConnectionsQuery(detailKey), [detailKey]));
  const findingQuery = useQueryRecords(useMemo(() => workflows.workflowFindingsQuery(detailKey), [detailKey]));
  const dependencyQuery = useQueryRecords(useMemo(() => workflows.workflowDependenciesQuery(detailKey), [detailKey]));
  const toolQuery = useQueryRecords(useMemo(() => workflows.workflowToolsQuery(detailKey), [detailKey]));
  const evidenceError =
    nodeQuery.error ??
    connectionQuery.error ??
    findingQuery.error ??
    dependencyQuery.error ??
    toolQuery.error;

  return (
    <PageFrame
      title="Workflows"
      subtitle="Search the live assessment register and open source, design, risk, validation, and deployment evidence."
    >
      <Panel title="Workflow assessment register" subtitle="Latest completed run, sorted by technical complexity">
        <div className="mb-4 grid gap-3 md:grid-cols-3">
          <label className="text-200 font-semibold">Search
            <input className="mt-1 w-full rounded-lg border bg-background p-2.5 font-normal" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Workflow name" />
          </label>
          <label className="text-200 font-semibold">Complexity
            <select className="mt-1 w-full rounded-lg border bg-background p-2.5 font-normal" value={complexity} onChange={(event) => setComplexity(event.target.value)}>
              {["All", "Low", "Medium", "High"].map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
          <label className="text-200 font-semibold">Fabric target
            <select className="mt-1 w-full rounded-lg border bg-background p-2.5 font-normal" value={target} onChange={(event) => setTarget(event.target.value)}>
              {["All", ...new Set(workflowQuery.records.map((record) => String(record.RecommendedTarget)))].map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
        </div>
        <DataState isLoading={workflowQuery.isLoading} error={workflowQuery.error} empty={!filtered.length} />
        {!!filtered.length && (
          <SimpleTable
            records={filtered}
            onSelect={(record) => setSelectedKey(String(record.WorkflowKey ?? record.WorkflowPath))}
            rowLabel={(record) => `Open workflow ${String(record.WorkflowPath)}`}
            columns={[
              { key: "WorkflowPath", label: "Workflow", render: (record) => <strong className="text-brand-foreground">{formatValue(record.WorkflowPath)}</strong> },
              { key: "SourcePlatform", label: "Source" },
              { key: "ComplexityBand", label: "Complexity", render: (record) => <Pill tone={record.ComplexityBand === "High" ? "danger" : record.ComplexityBand === "Medium" ? "warning" : "success"}>{formatValue(record.ComplexityBand)}</Pill> },
              { key: "RecommendedTarget", label: "Fabric target" },
              { key: "MigrationWave", label: "Wave" },
              { key: "RecommendationReason", label: "Key issue" },
            ]}
          />
        )}
      </Panel>
      {selected && (
        <WorkflowDialog
          workflow={selected}
          nodes={nodeQuery.records}
          connections={connectionQuery.records}
          findings={findingQuery.records}
          dependencies={dependencyQuery.records}
          tools={toolQuery.records}
          evidenceLoading={
            nodeQuery.isLoading ||
            connectionQuery.isLoading ||
            findingQuery.isLoading ||
            dependencyQuery.isLoading ||
            toolQuery.isLoading
          }
          evidenceError={evidenceError}
          onClose={() => setSelectedKey(undefined)}
          onOpenDeployment={onOpenDeployment}
        />
      )}
    </PageFrame>
  );
}

function WorkflowDialog({
  workflow,
  nodes,
  connections,
  findings,
  dependencies,
  tools,
  evidenceLoading,
  evidenceError,
  onClose,
  onOpenDeployment,
}: {
  workflow: QueryRecord;
  nodes: QueryRecord[];
  connections: QueryRecord[];
  findings: QueryRecord[];
  dependencies: QueryRecord[];
  tools: QueryRecord[];
  evidenceLoading: boolean;
  evidenceError?: Error;
  onClose: () => void;
  onOpenDeployment?: (workflowPath: string) => void;
}) {
  const [tab, setTab] = useState<DetailTab>("summary");
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);
  const tabs: { key: DetailTab; label: string }[] = [
    { key: "summary", label: "Summary" },
    { key: "source", label: "Source workflow" },
    { key: "design", label: "Fabric design" },
    { key: "risk", label: "Risk assessment" },
    { key: "validation", label: "Validation" },
    { key: "deployment", label: "Fabric deployment" },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-label={String(workflow.WorkflowPath)}>
      <div className="max-h-[92vh] w-full max-w-6xl overflow-auto rounded-xl border bg-background shadow-xl">
        <header className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b bg-background p-5">
          <div><p className="text-100 uppercase text-muted-foreground">Workflow details</p><h2 className="mt-1 text-section-title font-semibold">{formatValue(workflow.WorkflowPath)}</h2><p className="mt-1 text-200 text-muted-foreground">{formatValue(workflow.RecommendationReason)}</p></div>
          <button type="button" className="rounded-lg border p-2 hover:bg-hover" onClick={onClose} aria-label="Close workflow details"><X className="icon-size-200" /></button>
        </header>
        <div className="flex gap-2 overflow-x-auto border-b p-3" role="tablist" aria-label="Workflow detail sections">
          {tabs.map((item) => <button key={item.key} type="button" role="tab" aria-selected={tab === item.key} className={`shrink-0 rounded-lg px-3 py-2 text-200 font-semibold ${tab === item.key ? "bg-brand text-on-brand" : "hover:bg-hover"}`} onClick={() => setTab(item.key)}>{item.label}</button>)}
        </div>
        <div className="space-y-5 p-5">
          {tab === "summary" && <SummaryTab workflow={workflow} />}
          {tab === "source" && <SourceTab nodes={nodes} connections={connections} dependencies={dependencies} tools={tools} isLoading={evidenceLoading} error={evidenceError} />}
          {tab === "design" && <DesignTab workflow={workflow} />}
          {tab === "risk" && <RiskTab workflow={workflow} findings={findings} nodes={nodes} dependencies={dependencies} isLoading={evidenceLoading} error={evidenceError} />}
          {tab === "validation" && <ValidationTab />}
          {tab === "deployment" && <DeploymentTab workflowPath={String(workflow.WorkflowPath ?? "")} target={String(workflow.RecommendedTarget)} onOpenDeployment={onOpenDeployment} />}
        </div>
      </div>
    </div>
  );
}

function SummaryTab({ workflow }: { workflow: QueryRecord }) {
  const items = [
    ["Source path", workflow.WorkflowPath],
    ["Platform", workflow.SourcePlatform],
    ["Asset type", workflow.AssetType],
    ["Native ID", workflow.NativeId],
    ["Folder", workflow.Folder],
    ["Tools / connections", `${formatValue(workflow.ToolCount)} / ${formatValue(workflow.ConnectionCount)}`],
    ["Registry version", workflow.RegistryVersion],
  ];
  return <>
    <div className="grid gap-3 sm:grid-cols-3">
      <SummaryMetric label="Complexity" value={`${formatValue(workflow.ComplexityBand)} · ${formatValue(workflow.ComplexityScore)} points`} />
      <SummaryMetric label="Recommended target" value={formatValue(workflow.RecommendedTarget)} />
      <SummaryMetric label="Migration wave" value={formatValue(workflow.MigrationWave)} />
    </div>
    <Panel title="Source metadata"><dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{items.map(([label, value]) => <div key={label as string}><dt className="text-100 uppercase text-muted-foreground">{label as string}</dt><dd className="mt-1 break-words font-semibold">{formatValue(value)}</dd></div>)}</dl></Panel>
    <div className="rounded-lg border p-4 text-200 text-muted-foreground">Static assessment evidence only. Runtime, throughput, production volume, ownership, and failure history are not measured.</div>
  </>;
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border p-4"><p className="text-100 uppercase text-muted-foreground">{label}</p><strong className="mt-1 block">{value}</strong></div>;
}

function SourceTab({ nodes, connections, dependencies, tools, isLoading, error }: { nodes: QueryRecord[]; connections: QueryRecord[]; dependencies: QueryRecord[]; tools: QueryRecord[]; isLoading: boolean; error?: Error }) {
  return <>
    <DataState isLoading={isLoading} error={error} />
    <Panel title="Source workflow graph" subtitle={`${nodes.length} tools · ${connections.length} connections · bounded normalized evidence`}>
      <div className="flex gap-2 overflow-x-auto pb-2">
        {nodes.slice(0, 12).map((node, index) => <div key={`${String(node.NodeId)}-${index}`} className="flex shrink-0 items-center gap-2"><div className="w-40 rounded-lg border bg-muted/40 p-3"><strong className="block truncate">{formatValue(node.NodeName)}</strong><span className="text-100 text-muted-foreground">#{formatValue(node.NodeId)} · {formatValue(node.SupportCategory)}</span></div>{index < Math.min(nodes.length, 12) - 1 && <ArrowRight className="icon-size-200 text-muted-foreground" />}</div>)}
      </div>
      {nodes.length > 12 && <p className="mt-2 text-200 text-muted-foreground">Showing the first 12 nodes. Use the register below for complete evidence.</p>}
    </Panel>
    <Panel title="Tool mappings"><SimpleTable records={tools} columns={[{ key: "ToolName", label: "Tool" }, { key: "ToolCount", label: "Count" }, { key: "SupportCategory", label: "Mapping" }]} />{!tools.length && <p className="text-200 text-muted-foreground">No tool mappings recorded.</p>}</Panel>
    <Panel title="Tool register"><SimpleTable records={nodes} columns={[{ key: "NodeId", label: "ID" }, { key: "NodeName", label: "Tool" }, { key: "NodeLabel", label: "Label" }, { key: "SupportCategory", label: "Support" }, { key: "Disabled", label: "Disabled" }]} /></Panel>
    <div className="grid gap-5 xl:grid-cols-2">
      <Panel title="Connection register"><SimpleTable records={connections} columns={[{ key: "SourceNodeId", label: "Source" }, { key: "SourceAnchor", label: "Anchor" }, { key: "TargetNodeId", label: "Target" }, { key: "TargetAnchor", label: "Anchor" }]} /></Panel>
      <Panel title="Dependency graph"><SimpleTable records={dependencies} columns={[{ key: "DependencyReference", label: "Dependency" }, { key: "DependencyCount", label: "Count" }]} />{!dependencies.length && <p className="text-200 text-muted-foreground">No dependency references recorded.</p>}</Panel>
    </div>
  </>;
}

function DesignTab({ workflow }: { workflow: QueryRecord }) {
  return <>
    <Panel title="Recommended Fabric design" subtitle={formatValue(workflow.RecommendationReason)}>
      <div className="flex flex-wrap items-center gap-3">
        {["Source files and connections", "OneLake landing", formatValue(workflow.RecommendedTarget), "Reviewed orchestration"].map((item, index) => <div key={item} className="flex items-center gap-3"><div className="rounded-lg border bg-muted/40 px-4 py-3 font-semibold">{item}</div>{index < 3 && <ArrowRight className="icon-size-200 text-muted-foreground" />}</div>)}
      </div>
    </Panel>
    <Panel title="Implementation approach"><ol className="space-y-3"><ActionStep number="1" text="Resolve source schemas, identities, connections, and environment-specific dependencies." /><ActionStep number="2" text="Rebuild only explicitly supported transformations in the reviewed Fabric target." /><ActionStep number="3" text="Validate semantics, capacity, monitoring, restart, and rollback before deployment." /></ol></Panel>
  </>;
}

function ActionStep({ number, text }: { number: string; text: string }) {
  return <li className="flex gap-3"><span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand text-100 font-semibold text-on-brand">{number}</span><span>{text}</span></li>;
}

function RiskTab({ workflow, findings, nodes, dependencies, isLoading, error }: { workflow: QueryRecord; findings: QueryRecord[]; nodes: QueryRecord[]; dependencies: QueryRecord[]; isLoading: boolean; error?: Error }) {
  const redesign = nodes.filter((node) => /redesign|unsupported/i.test(String(node.SupportCategory))).length;
  const high = workflow.ComplexityBand === "High";
  return <>
    <DataState isLoading={isLoading} error={error} />
    <div className="grid gap-3 sm:grid-cols-3">
      <SummaryMetric label="Performance review" value={high ? "High priority" : "Standard priority"} />
      <SummaryMetric label="Compatibility review" value={redesign ? `${redesign} redesign nodes` : "No redesign nodes"} />
      <SummaryMetric label="Operational review" value={`${dependencies.length} dependencies`} />
    </div>
    <Panel title="Priority findings"><SimpleTable records={findings} columns={[{ key: "FindingType", label: "Type" }, { key: "FindingText", label: "Evidence" }, { key: "FindingCount", label: "Count" }]} />{!findings.length && <p className="text-200 text-muted-foreground">No bounded static findings recorded.</p>}</Panel>
    <div className="rounded-lg border p-4 text-200 text-muted-foreground">Unknown is not Low risk. Static priorities are not measured operational outcomes or a complete credential audit.</div>
  </>;
}

function ValidationTab() {
  return <div className="grid gap-5 lg:grid-cols-3"><Checklist title="Functional parity" items={["Compare schemas, types, row counts, and record-level reconciliation.", "Test nulls, expressions, joins, and rejected-row behavior.", "Validate every parameter combination and conditional route."]} /><Checklist title="Operational acceptance" items={["Confirm identities, bindings, permissions, and configuration.", "Test retries, restart, idempotency, logging, and alerting.", "Measure runtime and capacity with representative volumes."]} /><Checklist title="Cutover and rollback" items={["Agree acceptance thresholds and owner sign-off.", "Run source and target in parallel where authorized.", "Retain a tested rollback route until parity is accepted."]} /></div>;
}

function Checklist({ title, items }: { title: string; items: string[] }) {
  return <Panel title={title}><ol className="space-y-3">{items.map((item, index) => <ActionStep key={item} number={String(index + 1)} text={item} />)}</ol></Panel>;
}

function DeploymentTab({
  workflowPath,
  target,
  onOpenDeployment,
}: {
  workflowPath: string;
  target: string;
  onOpenDeployment?: (workflowPath: string) => void;
}) {
  return <><div className="rounded-lg border border-brand p-4"><strong>Dispatch-only deployment</strong><p className="mt-1 text-200 text-muted-foreground">The app validates an existing GitHub Actions or GitLab CI definition, creates a signed preview, and requires explicit confirmation. Provider credentials remain server-side.</p></div><Panel title="Deployment bundle"><dl className="grid gap-4 sm:grid-cols-3"><Brief label="Target" value={target} /><Brief label="Artifact root" value="generated-fabric-workflows" /><Brief label="Behavior" value="Fail, Skip, or Update" /></dl></Panel><button type="button" className="rounded-lg bg-brand px-4 py-3 font-semibold text-on-brand" onClick={() => onOpenDeployment?.(workflowPath)}>Open Fabric deployment</button></>;
}

function Brief({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-100 uppercase text-muted-foreground">{label}</dt><dd className="mt-1 font-semibold">{value}</dd></div>;
}
