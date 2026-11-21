import { portfolio } from "@/queries";
import { MetricCards, SemanticChart } from "@/components/semantic-visuals";
import { Panel, Pill } from "@/components/assessment-ui";
import { useQueryRecords } from "@/hooks/use-query-records";

export function PortfolioPage() {
  const { records } = useQueryRecords(portfolio.summary);
  const summary = records[0] ?? {};
  const assessed = Number(summary.AssessedAssets ?? 0);
  const manual = Number(summary.ManualReviewAssets ?? 0);
  const high = Number(summary.HighComplexityAssets ?? 0);
  const nativeReady = Math.max(assessed - manual, 0);

  return (
    <PageFrame
      title="Portfolio"
      subtitle="A governed view of estate readiness, complexity, and recommended Fabric targets."
    >
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
          { rawName: "[Pilot Assets]", title: "Pilot assets", subtitle: "Validate first" },
          { rawName: "[Redesign Assets]", title: "Redesign assets", subtitle: "Manual engineering path" },
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
