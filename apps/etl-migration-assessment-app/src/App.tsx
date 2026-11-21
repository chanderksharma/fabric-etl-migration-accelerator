import { useState } from "react";
import {
  BarChart3,
  ClipboardList,
  FileUp,
  Gauge,
  GitPullRequestArrow,
  Moon,
  PanelTopOpen,
  Rocket,
  Sun,
  Wrench,
} from "lucide-react";

import { useThemeContext } from "@/hooks/theme.context";
import { IntakeRunPage } from "@/pages/intake-run.page";
import { DeploymentPage } from "@/pages/deployment.page";
import { MigrationPage } from "@/pages/migration.page";
import { CapacityPage } from "@/pages/capacity.page";
import { PortfolioPage } from "@/pages/portfolio.page";
import { TechnicalPage } from "@/pages/technical.page";
import { WorkflowsPage } from "@/pages/workflows.page";

type PageKey = "intake" | "portfolio" | "workflows" | "migration" | "capacity" | "technical" | "deployment";

const navigation = [
  { key: "intake", label: "Intake & run", icon: FileUp },
  { key: "portfolio", label: "Portfolio", icon: BarChart3 },
  { key: "workflows", label: "Workflows", icon: ClipboardList },
  { key: "migration", label: "Migration plan", icon: GitPullRequestArrow },
  { key: "capacity", label: "Capacity planning", icon: Gauge },
  { key: "technical", label: "Technical evidence", icon: Wrench },
  { key: "deployment", label: "Fabric deployment", icon: Rocket },
] as const;

function App() {
  const [page, setPage] = useState<PageKey>("portfolio");
  const [deploymentWorkflowPath, setDeploymentWorkflowPath] = useState<string>();
  const { isDark, toggleTheme } = useThemeContext();
  const reportUrl = import.meta.env.VITE_REPORT_URL as string | undefined;

  return (
    <div className="min-h-full bg-background text-foreground">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-screen-2xl flex-col gap-4 px-4 py-5 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div>
            <p className="text-100 font-semibold uppercase tracking-widest text-brand-foreground">Microsoft Fabric</p>
            <h1 className="mt-1 font-page-title text-page-title text-emphasis-foreground">
              ETL Migration Assessment
            </h1>
          </div>
          <div className="flex items-center gap-2">
            {reportUrl && (
              <a
                className="inline-flex items-center gap-2 rounded-lg border bg-background px-3 py-2 text-200 font-semibold hover:bg-hover focus:outline-none focus:ring-2 focus:ring-ring"
                href={reportUrl}
                target="_blank"
                rel="noreferrer"
              >
                <PanelTopOpen className="icon-size-200" aria-hidden="true" />
                Power BI report
              </a>
            )}
            <button
              className="rounded-lg border bg-background p-2 hover:bg-hover focus:outline-none focus:ring-2 focus:ring-ring"
              type="button"
              onClick={toggleTheme}
              aria-label={isDark ? "Use light theme" : "Use dark theme"}
            >
              {isDark ? <Sun className="icon-size-200" /> : <Moon className="icon-size-200" />}
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto grid min-w-0 max-w-screen-2xl gap-6 overflow-hidden px-4 py-6 lg:grid-cols-[14rem_minmax(0,1fr)] lg:px-8">
        <nav className="flex min-w-0 max-w-full gap-2 overflow-x-auto lg:flex-col" aria-label="Application sections">
          {navigation.map((item) => {
            const Icon = item.icon;
            const selected = page === item.key;
            return (
              <button
                key={item.key}
                className={`inline-flex shrink-0 items-center gap-3 rounded-lg px-4 py-3 text-left text-300 font-semibold focus:outline-none focus:ring-2 focus:ring-ring ${
                  selected ? "bg-brand text-on-brand" : "hover:bg-hover"
                }`}
                type="button"
                aria-current={selected ? "page" : undefined}
                onClick={() => setPage(item.key)}
              >
                <Icon className="icon-size-200" aria-hidden="true" />
                {item.label}
              </button>
            );
          })}
        </nav>

        <main className="min-w-0">
          {page === "intake" && <IntakeRunPage />}
          {page === "portfolio" && <PortfolioPage />}
          {page === "workflows" && (
            <WorkflowsPage
              onOpenDeployment={(workflowPath) => {
                setDeploymentWorkflowPath(workflowPath);
                setPage("deployment");
              }}
            />
          )}
          {page === "migration" && <MigrationPage />}
          {page === "capacity" && <CapacityPage />}
          {page === "technical" && <TechnicalPage />}
          {page === "deployment" && (
            <DeploymentPage
              key={deploymentWorkflowPath ?? "default"}
              preselectedWorkflowPath={deploymentWorkflowPath}
            />
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
