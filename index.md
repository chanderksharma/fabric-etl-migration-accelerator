# Microsoft Fabric ETL Migration Accelerator

Welcome to the Chrysalis **Docs-as-Code** documentation portal for the **Microsoft Fabric ETL Migration Accelerator (`v1.0.0`)**.

This InnerSource IP Collection provides deterministic multi-source ETL estate discovery, canonical graph assessment, compiler-grounded Microsoft Fabric definition generation (**Dataflow Gen2**, **Fabric Notebook**, and **Data Pipeline**), and secretless **Microsoft Entra OIDC** CI/CD deployment for **Alteryx Designer**, **Informatica PowerCenter**, and **Informatica IDMC** workloads.

![Pluggable & Extensible ETL Migration Solution Architecture](docs/Architecture/arch-02-pluggable-solution-architecture.vsdx.fig.png)

## Major Sections

- **[Repository Overview (`README.md`)](README.md)** — Full functional scope, modular PyPI packages, compiler boundaries, quick-start commands, and InnerSource visibility scope.
- **[User Guide](docs/Guides/user-guide.md)** & **[Getting Started](docs/Guides/getting-started.md)** — End-to-end walkthroughs across the Fabric-native FEMA workspace, 7-tab React portfolio workbench (`Portfolio` assessment separated from `Fabric Deployment` code generation/dispatch), Windows desktop, and stateless `etl-assess` / `etl-fabric` CLIs.
- **[PyPI Packages & Publishing](docs/Guides/pypi-packages.md)** & **[Building Source & Target Plugins](docs/Guides/building-plugins.md)** — Installing, consuming, and publishing `etl-migration-core`, `etl-portfolio-assessment`, `etl-target-fabric`, and `fabric-etl-migration-accelerator`, plus SPI extension contracts.
- **[Installation & Runtime Modes](docs/Guides/installation.md)** — Wheel-based local runtime (`scripts/Start-LocalApp.ps1`), editable workstation setup, CLI-only mode, wheel-backed Windows desktop and Docker containers, and one-step FEMA workspace deployment (Lakehouse, Runtime 2.0 Environment, Notebook, 5-page Direct Lake Power BI report, and Fabric analyst app).
- **[Fabric CI/CD Setup](docs/Guides/fabric-ci-cd-setup.md)** — Secretless Microsoft Entra Workload Identity Federation (OIDC) deployment via GitHub Actions and GitLab CI.
- **[System Architecture](docs/Architecture/system-architecture.md)** & **[ADR-001](docs/Architecture/ADR-001-etl-source-adapters.md)** — Canonical ETL IR, target routing rules, and security boundaries.
- **[Threat Model](docs/Security/threat-model.md)** & **[Security Policy](SECURITY.md)** — STRIDE threat analysis, archive/XML safety caps, and SDL CI enforcement.
- **[Contributing Guide](CONTRIBUTING.md)** & **[Support](SUPPORT.md)** — Chrysalis InnerSource stakeholder roles, repository content structure, toolchain, and feedback channels.
