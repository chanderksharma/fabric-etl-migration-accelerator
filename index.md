# Microsoft Fabric ETL Migration Accelerator

Welcome to the Chrysalis **Docs-as-Code** documentation portal for the **Microsoft Fabric ETL Migration Accelerator (`v1.0.0`)**.

This InnerSource IP Collection provides deterministic multi-source ETL estate discovery, canonical graph assessment, compiler-grounded Microsoft Fabric definition generation (**Dataflow Gen2**, **Fabric Notebook**, and **Data Pipeline**), and secretless **Microsoft Entra OIDC** CI/CD deployment for **Alteryx Designer**, **Informatica PowerCenter**, and **Informatica IDMC** workloads.

![End-to-End Architecture Overview](docs/Architecture/arch-01-end-to-end-accelerator.vsdx.fig.png)

## Major Sections

- **[Repository Overview (`README.md`)](README.md)** — Full functional scope, compiler boundaries, quick-start commands, core team, and InnerSource visibility scope.
- **[Getting Started](docs/Guides/getting-started.md)** — 5-minute synthetic walkthrough using the React portfolio workbench and Typer CLI.
- **[Installation & Runtime Modes](docs/Guides/installation.md)** — Workstation setup, CLI-only mode, loopback Docker container, and one-step FEMA Fabric workspace deployment (Lakehouse, Runtime 2.0 Environment, Notebook, Direct Lake Power BI report, and Fabric analyst app).
- **[Fabric CI/CD Setup](docs/Guides/fabric-ci-cd-setup.md)** — Secretless Microsoft Entra Workload Identity Federation (OIDC) deployment via GitHub Actions and GitLab CI.
- **[System Architecture](docs/Architecture/system-architecture.md)** & **[ADR-001](docs/Architecture/ADR-001-etl-source-adapters.md)** — Canonical ETL IR, target routing rules, and security boundaries.
- **[Threat Model](docs/Security/threat-model.md)** & **[Security Policy](SECURITY.md)** — STRIDE threat analysis, archive/XML safety caps, and SDL CI enforcement.
- **[Contributing Guide](CONTRIBUTING.md)** & **[Support](SUPPORT.md)** — Chrysalis InnerSource stakeholder roles, repository content structure, toolchain, and feedback channels.
