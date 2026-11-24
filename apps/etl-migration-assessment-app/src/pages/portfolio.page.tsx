import { portfolio, workflows } from "@/queries";
import { MetricCards, SemanticChart } from "@/components/semantic-visuals";
import { DataState, Panel, Pill, SimpleTable } from "@/components/assessment-ui";
import { useAssessmentRunContext } from "@/hooks/assessment-run.context";
import { downloadCsv, downloadJson } from "@/lib/download";
import { formatValue } from "@/lib/format-value";
import { waveLabel } from "@/lib/migration-wave";
import { useQueryRecords } from "@/hooks/use-query-records";

export function PortfolioPage({
  onOpenDeployment,
  onOpenWorkflows,
}: {
  onOpenDeployment?: () => void;
  onOpenWorkflows?: (workflowPath?: string) => void;
} = {}) {
  const summaryQuery = useQueryRecords(portfolio.summary);
  const registerQuery = useQueryRecords(workflows.register);
  const { activeRunId, runs } = useAssessmentRunContext();
  const selectedRun = activeRunId
    ? runs.find((run) => run.runId === activeRunId)
    : runs[0];
  if (summaryQuery.isLoading || summaryQuery.error || !summaryQuery.records.length) {
    return (
      <PageFrame
        title="Portfolio"
        subtitle="A governed view of estate readiness, complexity, and recommended Fabric targets."
      >
        <DataState
          isLoading={summaryQuery.isLoading}
          error={summaryQuery.error}
          empty={!summaryQuery.isLoading && !summaryQuery.error && !summaryQuery.records.length}
        />
      </PageFrame>
    );
  }
  const summary = summaryQuery.records[0];
  const assessed = Number(summary.AssessedAssets ?? 0);
  const manual = Number(summary.ManualReviewAssets ?? 0);
  const high = Number(summary.HighComplexityAssets ?? 0);
  const nativeReady = Math.max(assessed - manual, 0);
  const topWorkflows = registerQuery.records.slice(0, 5);

  return (
    <PageFrame
      title="Portfolio"
      subtitle="A governed view of estate readiness, complexity, and recommended Fabric targets."
    >
      <div className="flex flex-wrap justify-end gap-2">
        <button
          type="button"
          className="rounded-lg border bg-background px-3 py-2 text-200 font-semibold hover:bg-hover"
          onClick={() => downloadJson("portfolio-summary.json", {
            run: selectedRun,
            summary,
          })}
        >
          Export summary JSON
        </button>
        <button
          type="button"
          className="rounded-lg border bg-background px-3 py-2 text-200 font-semibold hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!registerQuery.records.length}
          onClick={() => downloadCsv(
            "portfolio-assessment.csv",
            [
              "WorkflowPath",
              "SourcePlatform",
              "ComplexityScore",
              "ComplexityBand",
              "RecommendedTarget",
              "EstimatedEffortDays",
              "MigrationWave",
              "RecommendationReason",
            ],
            registerQuery.records,
          )}
        >
          Export portfolio CSV
        </button>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card p-4 text-200" role="note">
        <div>
          <strong>
            Routing basis: {!selectedRun
              ? "unavailable"
              : selectedRun.routingBasis === "static_mapping"
                ? "static mapping"
                : "compiler-confirmed Fabric fit"}.
          </strong>
          <span className="ml-1 text-muted-foreground">
            {!selectedRun
              ? "Run metadata is still loading; target, wave, effort, and capacity must not be used for delivery yet."
              : selectedRun.routingBasis === "static_mapping"
              ? "Assessment did not compile code. Confirm Fabric fit from CI/CD dispatch before using target, wave, effort, or capacity for delivery."
              : "Target, wave, effort, and capacity use compiler-confirmed routing."}
          </span>
        </div>
        {selectedRun?.routingBasis === "static_mapping" && onOpenDeployment && (
          <button
            type="button"
            className="shrink-0 rounded-lg border bg-background px-3 py-1.5 text-200 font-semibold hover:bg-hover"
            onClick={onOpenDeployment}
          >
            Confirm Fabric fit →
          </button>
        )}
      </div>
      <div className="rounded-xl border border-brand bg-card p-5 shadow-container-2">
        <p className="text-100 font-semibold uppercase tracking-widest text-brand-foreground">Leadership recommendation</p>
        <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <h2 className="text-section-title font-semibold">Proceed conditionally with the native-ready portfolio</h2>
            <p className="mt-2 text-300 text-muted-foreground">
              {nativeReady} of {assessed || "the assessed"} workflows have a compiler-grounded Fabric route.
              Resolve {manual} manual-review item{manual === 1 ? "" : "s"}, assign business ownership,
              and validate parity before scale-out.
            </p>
          </div>
          <Pill tone={manual > 0 ? "warning" : "success"}>{manual > 0 ? "Conditional proceed" : "Proceed"}</Pill>
        </div>
      </div>

      <div className="grid gap-(--grid-gap) xl:grid-cols-2">
        <Panel title="Decision brief" subtitle="Approval boundary for the latest completed assessment">
          <dl className="grid gap-4 sm:grid-cols-2">
            <BriefItem label="Decision requested" value="Approve controlled mobilization" />
            <BriefItem label="Funding boundary" value="Prerequisites and representative pilot" />
            <BriefItem label="Conditions" value="Owners, parity thresholds, capacity, and rollback" />
            <BriefItem label="Next approval gate" value="Pilot exit review before scale-out" />
          </dl>
        </Panel>
        <Panel title="Leadership scorecard" subtitle="Readiness from available deterministic evidence">
          <div className="space-y-3">
            <Score label="Technology readiness" tone={manual ? "warning" : "success"} text={`${nativeReady} of ${assessed} workflows have a native route.`} />
            <Score label="Business ownership" tone="danger" text="Owner, criticality, and SLA evidence are not persisted." />
            <Score label="Business case" tone="danger" text="Cost, savings, and benefit baselines require separate approval." />
            <Score label="Delivery governance" tone={high ? "warning" : "success"} text={`${high} high-complexity workflows require enhanced validation.`} />
          </div>
        </Panel>
      </div>

      <MetricCards
        definition={portfolio.summary}
        metrics={[
          { rawName: "[Assessed Assets]", title: "Assessed assets", subtitle: "Latest completed run" },
          { rawName: "[High Complexity Assets]", title: "High complexity", subtitle: "Requires focused design" },
          { rawName: "[Wave 2 Assets]", title: "Wave 2 (Pilot)", subtitle: "Validate first" },
          { rawName: "[Wave 4 Assets]", title: "Wave 4 (Redesign)", subtitle: "Manual engineering path" },
          { rawName: "[Estimated Remaining Effort]", title: "Remaining effort", subtitle: "Deterministic person-days" },
        ]}
      />
      <div className="grid gap-(--grid-gap) xl:grid-cols-3">
        <SemanticChart
          definition={portfolio.complexityDistribution}
          title="Complexity distribution"
          subtitle="Assets by deterministic complexity band"
        />
        <SemanticChart
          definition={portfolio.targetDistribution}
          title="Recommended Fabric targets"
          subtitle="Compiler-grounded implementation route"
        />
        <SemanticChart
          definition={portfolio.waveDistribution}
          title="Migration wave distribution"
          subtitle="Evidence-based sequence"
        />
      </div>

      {topWorkflows.length > 0 && (
        <Panel
          title="Workflows with highest technical complexity"
          subtitle="Prioritized by static raw complexity score; does not represent business criticality."
        >
          <div className="mb-3 flex justify-end">
            {onOpenWorkflows && (
              <button
                type="button"
                className="text-200 font-semibold text-brand-foreground underline"
                onClick={() => onOpenWorkflows()}
              >
                View workflow register →
              </button>
            )}
          </div>
          <SimpleTable
            records={topWorkflows}
            onSelect={
              onOpenWorkflows
                ? (record) => onOpenWorkflows(String(record.WorkflowPath ?? ""))
                : undefined
            }
            rowLabel={(record) => `Open workflow ${String(record.WorkflowPath ?? "")}`}
            columns={[
              { key: "WorkflowPath", label: "Workflow", render: (record) => <strong className="text-brand-foreground">{formatValue(record.WorkflowPath)}</strong> },
              { key: "ComplexityScore", label: "Score" },
              { key: "ComplexityBand", label: "Complexity", render: (record) => <Pill tone={record.ComplexityBand === "High" ? "danger" : record.ComplexityBand === "Medium" ? "warning" : "success"}>{formatValue(record.ComplexityBand)}</Pill> },
              { key: "MigrationWave", label: "Wave", render: (record) => waveLabel(record.MigrationWave) },
              { key: "RecommendedTarget", label: "Fabric target" },
              { key: "EstimatedEffortDays", label: "Remaining effort", render: (record) => `${Number(record.EstimatedEffortDays ?? 0).toFixed(1)}d` },
              { key: "RecommendationReason", label: "Why it matters" },
            ]}
          />
        </Panel>
      )}

      <div className="grid gap-(--grid-gap) xl:grid-cols-2">
        <Panel title="Immediate leadership actions" subtitle="Actions required before broader delivery">
          <ol className="space-y-4">
            <Action number="1" title="Name the sponsor and workflow owners" text="Assign business accountability, criticality, and service expectations." />
            <Action number="2" title="Commission the business case" text="Validate capacity, migration cost, legacy savings, and expected benefits." />
            <Action number="3" title="Authorize a controlled pilot" text="Approve entry criteria and require measured functional and operational exit evidence." />
          </ol>
        </Panel>
        <Panel title="Assessment confidence and evidence gaps" subtitle="Interpretation boundary">
          <p className="text-300 text-muted-foreground">
            Recommendations use static workflow evidence. Business criticality, ownership, run frequency,
            production volumes, operating cost, runtime history, and benefit realization are not available
            in the normalized assessment model. Unknown values are not Low risk.
          </p>
        </Panel>
      </div>
    </PageFrame>
  );
}

function BriefItem({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-100 uppercase text-muted-foreground">{label}</dt><dd className="mt-1 font-semibold">{value}</dd></div>;
}

function Score({ label, tone, text }: { label: string; tone: "success" | "warning" | "danger"; text: string }) {
  return <div className="rounded-lg border p-3"><div className="flex items-center justify-between gap-2"><strong>{label}</strong><Pill tone={tone}>{tone === "success" ? "Green" : tone === "warning" ? "Amber" : "Red"}</Pill></div><p className="mt-1 text-200 text-muted-foreground">{text}</p></div>;
}

function Action({ number, title, text }: { number: string; title: string; text: string }) {
  return <li className="flex gap-3"><span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand font-semibold text-on-brand">{number}</span><div><strong>{title}</strong><p className="mt-1 text-200 text-muted-foreground">{text}</p></div></li>;
}

export function PageFrame({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-6">
      <header>
        <h1 className="font-page-title text-page-title text-emphasis-foreground">{title}</h1>
        <p className="mt-1 font-page-subtitle text-page-subtitle text-muted-foreground">{subtitle}</p>
      </header>
      {children}
    </section>
  );
}
