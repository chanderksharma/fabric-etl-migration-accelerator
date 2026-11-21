---
title: PyPI Packages and Publishing Guide
description: Install, consume, build, validate, and publish etl-migration-core, etl-portfolio-assessment, etl-target-fabric, and fabric-etl-migration-accelerator packages
ms.date: 2026-11-21
ms.topic: how-to
---

## Package overview

The repository is organized as a `uv` workspace producing four independent Python distributions with strict acyclic dependencies:

| PyPI package | Import module | Runtime dependencies | Primary use case |
| :--- | :--- | :--- | :--- |
| `etl-migration-core` | `etl_migration_core` | `pydantic`, `defusedxml` | Canonical `EtlPackage` IR, secure staging, source adapters, and target SPI |
| `etl-portfolio-assessment` | `etl_portfolio_assessment` | `etl-migration-core` | Target-neutral complexity, base effort, workload profiles, redacted evidence, `etl-assess` CLI |
| `etl-target-fabric` | `etl_target_fabric` | `etl-migration-core` | Microsoft Fabric evaluator, F-SKU capacity model, M/PySpark/Pipeline compilers, artifact writer, `etl-fabric` CLI |
| `fabric-etl-migration-accelerator` | `accelerator` | Core + assessment + Fabric + `fastapi`, `uvicorn`, `typer`, `pyjwt` | Local React/FastAPI server, SQLite WAL `RunService`, Typer `tool` CLI, CI dispatchers, Desktop utility |

All packages require Python 3.13 or later (`requires-python = ">=3.13"`).

## Install packages

### From a configured PyPI or Azure Artifacts feed

Install only the capability layer your environment requires:

```bash
# Target-neutral portfolio assessment only (no FastAPI or Fabric deps)
pip install etl-portfolio-assessment

# Microsoft Fabric evaluator, capacity sizing, and compilers
pip install etl-target-fabric

# Portfolio assessment with Microsoft Fabric provider plugin included
pip install "etl-portfolio-assessment[fabric]"

# Full local analyst web UI, SQLite RunService, and CLI
pip install fabric-etl-migration-accelerator
```

Using `uv`:

```bash
uv pip install etl-portfolio-assessment etl-target-fabric
```

### From an internal Azure Artifacts feed

Configure `pip` or `uv` with your organization's internal index URL:

```bash
pip install --index-url https://pkgs.dev.azure.com/<org>/<project>/_packaging/<feed>/pypi/simple/ etl-portfolio-assessment etl-target-fabric
```

### Run the local analyst app from built wheels

Launch the local web UI (`apps/web` + `fabric-etl-migration-accelerator`) or Windows desktop app strictly from the four built `.whl` files in `dist/` (no editable workspace source links):

```powershell
pwsh -NoProfile -File scripts\Start-LocalApp.ps1
```

Pass `-VerifyOnly` to test wheel installation, non-editable metadata, and live `/health` + `/` + `/api/targets` endpoints cleanly. See [Installation and Runtime Modes](installation.md) for container (`Dockerfile`) and Windows desktop (`scripts\Build-Desktop.ps1`) wheel builds.

### From locally built wheels

Build all distributions from the repository root and install in an isolated environment:

```powershell
uv build --all-packages
uv run --isolated --no-project `
  --with .\dist\etl_migration_core-1.0.0-py3-none-any.whl `
  --with .\dist\etl_portfolio_assessment-1.0.0-py3-none-any.whl `
  etl-assess assess .\alteryx-workflows
```

## Python SDK quickstart

### Target-neutral portfolio assessment

```python
from pathlib import Path
from etl_portfolio_assessment.service.application import PortfolioAssessmentApplication

app = PortfolioAssessmentApplication()
result = app.assess_neutral(Path("alteryx-workflows"))
print(result.workflow_count, result.failed_count)
```

### Microsoft Fabric evaluation and compilation

```python
from pathlib import Path
from etl_migration_core.sources.defaults import create_default_registry
from etl_migration_core.targets import create_target_registry
from etl_target_fabric.compilers.alteryx import generate_candidate

targets = create_target_registry()
fabric = targets.require_implemented("fabric", capability="codegen")

sources = create_default_registry()
workflow = Path("alteryx-workflows/sample_alteryx_workflow.yxmd")
detected = sources.detect(workflow, workflow.name)
package = sources.parse(workflow, detected.match)

evaluation = fabric.evaluator().evaluate_asset(
    package,
    package.assets[0],
    base_reason="Static analysis",
)
candidate = generate_candidate(workflow, "dataflow")
print(evaluation.recommended_target, candidate.validation_state)
```

## Build and validate packages locally

Run the full quality, build, metadata, and isolated-wheel verification sequence before publishing:

```powershell
uv run --extra dev ruff check src packages tests
uv run --extra dev mypy
uv run --extra dev pytest --cov-fail-under=80
uv build --all-packages
uvx twine check dist/*.whl dist/*.tar.gz
```

Verify each library wheel runs cleanly without `fastapi` or sibling packages when optional:

```powershell
uv run --isolated --no-project `
  --with .\dist\etl_migration_core-1.0.0-py3-none-any.whl `
  --with .\dist\etl_portfolio_assessment-1.0.0-py3-none-any.whl `
  python -c "import sys; from pathlib import Path; from etl_portfolio_assessment.service.application import PortfolioAssessmentApplication; res = PortfolioAssessmentApplication().assess_neutral(Path('alteryx-workflows')); assert res.workflow_count > 0 and 'fastapi' not in sys.modules"

uv run --isolated --no-project `
  --with .\dist\etl_migration_core-1.0.0-py3-none-any.whl `
  --with .\dist\etl_target_fabric-1.0.0-py3-none-any.whl `
  python -c "import sys; from etl_migration_core.targets import create_target_registry; reg = create_target_registry(); assert reg.require_implemented('fabric', capability='codegen').platform_id == 'fabric'; assert 'fastapi' not in sys.modules"
```

## Publish packages

### Governance and license prerequisite

> [!CAUTION]
> The repository [LICENSE](../../LICENSE) currently restricts distribution to Microsoft internal use and InnerSource reuse. Publish to an internal Azure Artifacts PyPI feed while internal, or obtain Microsoft Legal and Open Source Programs Office (OSPO) approval and apply an OSI-approved license before publishing to public PyPI.

### Option A: Publish to an internal Azure Artifacts PyPI feed

1. Create or reuse a Python feed in Azure Artifacts inside your Microsoft organization.
2. Authenticate using `artifacts-keyring` or a scoped feed token and upload the checked distributions:

   ```powershell
   uvx twine upload --repository-url https://pkgs.dev.azure.com/<org>/<project>/_packaging/<feed>/pypi/upload/ dist/*.whl dist/*.tar.gz
   ```

### Option B: Automated GitHub Actions release to PyPI (OIDC Trusted Publishing)

The workflow [.github/workflows/publish-packages.yml](../../.github/workflows/publish-packages.yml) builds all four packages, verifies `twine check` and isolated wheel smoke tests, and publishes using OpenID Connect (OIDC) Trusted Publishing without storing long-lived PyPI API tokens.

1. Reserve the package names (`etl-migration-core`, `etl-portfolio-assessment`, `etl-target-fabric`, `fabric-etl-migration-accelerator`) on PyPI or TestPyPI and configure a Trusted Publisher for your GitHub repository, workflow `publish-packages.yml`, and environment `pypi`.
2. In your GitHub repository settings, create the protected `pypi` environment (add required reviewers) and set repository variable `PYPI_PUBLISH_ENABLED` to `true`.
3. Bump matching `version` fields across the root `pyproject.toml`, `src/accelerator/__init__.py`, and `packages/*/pyproject.toml` + `__init__.py` files, then push a release tag matching `v*` (for example `v1.0.0`).
4. Approve the `pypi` environment deployment when prompted in GitHub Actions.

## Related documentation

* [User Guide](user-guide.md) for end-to-end FEMA, UI, and CLI workflows
* [Building Source and Target Plugins](building-plugins.md) for extending `etl_migration.sources` and `etl_migration.targets`
* [Pluggable Architecture Implementation Plan](../Planning/pluggable-architecture-implementation-plan.md) for package boundaries and separation of duties
