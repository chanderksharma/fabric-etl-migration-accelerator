---
title: Developer Contribution Guide
description: Practical workflows for fixing bugs, adding features, and extending source and target support
ms.date: 2026-11-22
ms.topic: how-to
---

## Start here

Use this guide to find the right code, make a focused change, and verify it.
Follow the issue-first and pull request process in
[Contributing](../../CONTRIBUTING.md). Use only synthetic examples in issues,
fixtures, screenshots, and generated artifacts. Never commit customer exports,
credentials, tenant or workspace identifiers, or local user paths.

The accelerator reads untrusted workflow definitions. It must not execute
source workflows, scripts, expressions, or SQL. Unsupported semantics must
remain visible as diagnostics, not be silently translated or emitted as
deployable artifacts. Generated definitions require bindings and independent
semantic parity validation before promotion.

## Find the right layer

| What you are changing | Start here | Related tests |
| --- | --- | --- |
| File, folder, archive, or XML intake | [Discovery service](../../packages/etl-migration-core/src/etl_migration_core/intake/discovery.py) and [intake domain](../../packages/etl-migration-core/src/etl_migration_core/intake/domain.py) | [Discovery tests](../../tests/test_discovery.py) |
| Source parsing and canonical ETL graphs | [Source adapters](../../packages/etl-migration-core/src/etl_migration_core/sources/) and [IR contracts](../../packages/etl-migration-core/src/etl_migration_core/contracts/ir.py) | [Source adapter tests](../../tests/test_source_adapters.py) and product-specific adapter tests |
| Target-neutral complexity, effort, or evidence | [Assessment engine](../../packages/etl-portfolio-assessment/src/etl_portfolio_assessment/assessment/engine.py), [workload profile](../../packages/etl-portfolio-assessment/src/etl_portfolio_assessment/assessment/workload_profile.py), and [evidence extractor](../../packages/etl-portfolio-assessment/src/etl_portfolio_assessment/evidence/extractor.py) | [Assessment package tests](../../packages/etl-portfolio-assessment/tests/test_assessment_package.py) and [target tests](../../tests/test_targets.py) |
| Fabric fit, capacity, or generated definitions | [Fabric assessment](../../packages/etl-target-fabric/src/etl_target_fabric/assessment/), [capacity model](../../packages/etl-target-fabric/src/etl_target_fabric/capacity/), and [compilers](../../packages/etl-target-fabric/src/etl_target_fabric/compilers/) | [ETL assessment](../../tests/test_etl_assessment.py), [capacity](../../tests/test_capacity.py), and [generation tests](../../tests/test_etl_generation.py) |
| Local API, durable runs, or CLI | [API](../../src/accelerator/server/api.py) (routes), [upload staging](../../src/accelerator/server/uploads.py), [deployment resolution](../../src/accelerator/server/deployment.py), [run service](../../src/accelerator/runtime/runs.py) (orchestration), [SQLite store and retention](../../src/accelerator/runtime/store.py), [cache keys and snapshot IDs](../../src/accelerator/runtime/identity.py), [publications](../../src/accelerator/runtime/publication.py), [settings and logging](../../src/accelerator/settings.py), and [CLI](../../src/accelerator/cli/app.py) | [API](../../tests/test_api.py), [CLI](../../tests/test_cli.py), [resilience and retention](../../tests/test_runtime_resilience.py), and [multi-source application tests](../../tests/test_multisource_application.py) |
| Generation jobs, candidate cache, or the neutral artifact projection | [Run service](../../src/accelerator/runtime/runs.py), [candidate cache keys](../../src/accelerator/runtime/identity.py), [ArtifactSet projection](../../src/accelerator/runtime/artifacts.py), and the [ArtifactSet contract](../../packages/etl-migration-core/src/etl_migration_core/contracts/artifacts.py) | [Generation hardening](../../tests/test_generation_hardening.py) and the [sample-estate digest](../../tests/test_golden_digest.py) |
| Local analyst experience | [Web app](../../apps/web/src/) | [App tests](../../apps/web/src/App.test.tsx) and [workspace tests](../../apps/web/src/Workspace.test.tsx) |
| Fabric-native intake and reporting | [Fabric analyst app](../../apps/etl-migration-assessment-app/src/), [app functions](../../apps/etl-migration-assessment-app/rayfin/functions/src/), and [assessment notebook](../../notebooks/fabric-portfolio-assessment.ipynb) | App `*.spec.ts` and `*.spec.tsx` tests; [FEMA deployment tests](../../tests/test_fema_deployment.py) |
| CI dispatch or Fabric deployment | [Delivery modules](../../src/accelerator/delivery/), [deployment script](../../scripts/Deploy-FabricArtifacts.ps1), and [CI/CD setup](fabric-ci-cd-setup.md) | [GitHub](../../tests/test_github_deployment.py), [GitLab](../../tests/test_gitlab_deployment.py), and [acceptance tests](../../tests/test_acceptance.py) |

The canonical intermediate representation (IR) describes source assets and
graphs. A service provider interface (SPI) is a contract implemented by a
plugin. See the [source adapter protocol](../../packages/etl-migration-core/src/etl_migration_core/sources/base.py)
and [target SPI](../../packages/etl-migration-core/src/etl_migration_core/contracts/spi.py).
The [architecture](../Architecture/system-architecture.md) and
[plugin guide](building-plugins.md) describe their boundaries.
Host registration calls `require_compatible_spi`. Omit `spi_version` to mean
`1.0.0`. A declaration such as `2.0.0` fails registration and is reported as a
plugin load failure. Folder uploads accept at most 10,000 named files. The route
class raises only that multipart file cap. The 100 MiB browser upload budget is
unchanged. Power Query string literals go
through `etl_migration_core.m_literals.m_string`. Integer half-even effort goes
through `etl_migration_core.planning`. Do not keep a second copy of either rule.

## Fix a bug

1. Reproduce the observed behavior with a minimal synthetic fixture. Record
   the expected and actual result in the issue; do not attach customer data.
2. Trace the behavior from intake through the relevant assessment, generation,
   API, or UI layer. Identify the first incorrect result rather than masking
   it in a later layer.
3. Add a focused regression test that fails for the defect. Include a relevant
   error or boundary case, such as a malformed archive or unsupported operation.
4. Fix the producer and keep dependent call sites consistent. Preserve
   compatibility and surface failures through the existing diagnostics.
5. Run the focused tests and a relevant end-to-end check. Update user or
   developer documentation if the observable behavior changes.

For example, if a workflow inside a ZIP is missing, test both loose-file and
archive discovery paths before changing the parser. If a generated candidate
is incorrect, verify the normalized graph and target support before changing
the renderer.

## Add a feature or a transformation

1. Define the user-visible outcome, supported inputs, failure cases, and
   acceptance criteria in an issue. Decide which runtimes need the feature:
   local CLI/API and UI, stateless packages, or Fabric-native app and notebook.
2. Keep source facts in the canonical model and neutral assessment. Put
   target-specific support, cost, capacity, and artifact syntax in the
   relevant target provider. Keep deployment optional.
3. Add synthetic supported and unsupported examples. For a compiler feature,
   test that supported semantics are preserved and that unsupported cases
   produce diagnostics without create-item envelopes.
4. Check versioned IR, rules, adapter and output schemas, snapshot/cache
   compatibility, and artifact provenance when changing their meaning.
   Preserve existing clients and cached runs or reject incompatibilities
   explicitly.
5. Update the affected API, CLI, UI, reports, documentation, and tests as
   needed. A change to one runtime does not automatically update the others.
6. Run focused tests, then an end-to-end check across the affected surfaces.

Fabric support classifications live in the
[support matrix](../../packages/etl-target-fabric/src/etl_target_fabric/assessment/support_matrix.py).
A classification alone does not prove that the compiler supports a
particular configuration. Test generated artifacts and unsupported cases.

## Extend a source system

For example, adding SSIS `.dtsx` intake requires more than registering an
adapter. Product SSIS semantics are not implemented. The
[synthetic SSIS example](../../examples/plugins/synthetic-ssis/README.md)
extracts bounded metadata for a local neutral run. It does not interpret SSIS.

1. Agree on the initial file formats, package boundaries, transformations,
   control flow, and unsupported cases. Add synthetic fixtures first.
2. Implement the [source adapter protocol](../../packages/etl-migration-core/src/etl_migration_core/sources/base.py):
   probe without executing input, then parse into versioned `EtlPackage`,
   `EtlAsset`, and mapping or orchestration graphs. Preserve source IDs,
   locations, dependencies, and unresolved semantics. Use bounded, secure XML
   parsing.
3. Register a built-in adapter in [source defaults](../../packages/etl-migration-core/src/etl_migration_core/sources/defaults.py),
   or package an external adapter under the `etl_migration.sources` entry
   point. The current [source platform enum](../../packages/etl-migration-core/src/etl_migration_core/contracts/ir.py)
   is closed, so a new platform also requires a compatible core contract.
   Omit `spi_version`, or set a version compatible with `IR_SPI_VERSION`
   (`1.0.0`). See [Building Source and Target Plugins](building-plugins.md).
4. Update [intake domain](../../packages/etl-migration-core/src/etl_migration_core/intake/domain.py)
   and [discovery](../../packages/etl-migration-core/src/etl_migration_core/intake/discovery.py)
   for new files and archive members. Preserve size, archive, path, staging,
   and deduplication safeguards. Today these paths use explicit extension and
   source-identity logic; plugin registration alone does not admit new formats.
5. Review the [neutral engine](../../packages/etl-portfolio-assessment/src/etl_portfolio_assessment/assessment/engine.py),
   [workload profile](../../packages/etl-portfolio-assessment/src/etl_portfolio_assessment/assessment/workload_profile.py),
   and [profile contract](../../packages/etl-migration-core/src/etl_migration_core/contracts/spi.py).
   The current profile distinguishes Alteryx from Informatica only. Unknown
   neutral operations otherwise default to tabular classification, so mark
   unrecognized or problematic source constructs with appropriate issues and
   test their classification.
6. Integrate the required runtime surfaces. The current
   [run service](../../src/accelerator/runtime/runs.py) uses Fabric assessment
   and Informatica capacity logic on its non-Alteryx path; do not route a new
   source through it unchanged. Update local intake and, if in scope, the
   Fabric-native picker and upload validation.
7. Test loose files, archives, ambiguous detection, malformed input, canonical
   graphs, neutral assessment, evidence redaction, and existing sources.
   Test target support separately; successful intake is not proof of
   conversion support.

## Extend a target platform

For example, Databricks is currently a fail-closed placeholder, not a
working destination.

1. Define a narrow supported operation set, artifact format, diagnostics,
   required bindings, and validation strategy. Start with evaluation before
   generation and deployment.
2. Implement a target provider and evaluator using the
   [target SPI](../../packages/etl-migration-core/src/etl_migration_core/contracts/spi.py).
   Keep target fit and capacity separate from neutral portfolio facts.
   Advertise only capabilities that are implemented and tested.
3. Register the provider in the `etl_migration.targets` entry-point group.
   The [target registry](../../packages/etl-migration-core/src/etl_migration_core/targets/registry.py)
   can replace a placeholder when the implementing provider is installed.
   Check IR-version compatibility and retain fail-closed behavior when the
   provider or capability is unavailable. Omit `spi_version`, or set a version
   compatible with `IR_SPI_VERSION` (`1.0.0`). A future writer should consume
   [ArtifactSet](../../packages/etl-migration-core/src/etl_migration_core/contracts/artifacts.py)
   rather than Fabric paths. The current projection leaves `files` empty and
   does not connect plugin generation to the portal.
4. Implement and test deterministic generation and artifact packaging for
   supported operations. Emit explicit diagnostics for unsupported semantics;
   never treat plugin discovery as semantic validation.
5. Integrate evaluation and, when implemented, generation and deployment
   through the application, API, CLI, and UI. The current provider protocol
   exposes metadata and an evaluator; the local run service and generation
   routes are Fabric-oriented. Registering a provider does not by itself
   dispatch generation or deployment to it.
6. Add provider, comparison, artifact, compatibility, and end-to-end tests.
   Keep target deployment separate from CI delivery transport, and require
   approved environments and appropriate verification for any live deployment.

See [Building Source and Target Plugins](building-plugins.md) for entry-point
examples and [PyPI Packages and Publishing](pypi-packages.md) for packaging.
For a new wheel, review workspace dependencies, tests, build and publishing,
and any local or Fabric runtime bundles that must include it.

## Queue generation without writing files

Use this path when you need candidates for a completed run and must not touch
the shared artifact tree.

1. Confirm the assessment run is `completed`. Jobs and synchronous generate
   both reject an incomplete run.
2. Queue one target with `POST /api/runs/{id}/jobs?target=notebook`. Accepted
   values are `notebook`, `dataflow`, and `pipeline`. The route returns `202`.
   There is no CLI equivalent, and the portal does not call it.
3. Poll `GET /api/runs/{id}/jobs`. A completed job carries candidates. The
   worker calls the compiler path and must not call `write_candidates`.
4. Read one workflow with
   `GET /api/runs/{id}/workflows/{index}/candidates`. The index is zero-based
   in the confirmed snapshot.
5. Treat `artifact:` cache rows as the target-neutral projection. They are not
   a Fabric package. `candidate:` rows are the Fabric `Candidate` JSON.

An unexpected exception in one workflow becomes a blocked candidate prefixed
with `unexpected generation fault` and is not cached. Re-raise `OSError`,
`sqlite3.Error`, and `ValueError`. A blocked candidate cannot honestly name an
external plugin platform, because `Candidate.source_platform` is the closed
source enum. Unsupported-source generation must keep raising `ValueError`.

## Change the local run database

The run database is owned by the [SQLite store](../../src/accelerator/runtime/store.py)
and lives in users' `.accelerator` folders, so a schema change must work on state that an
earlier release already wrote. The current version is 7. Schema 7 appends
`generation_jobs`. Candidate and ArtifactSet JSON stay in the existing `cache`
table. Do not add those rows to the job table's writer.

1. Append a step to `MIGRATIONS` with the next version number and raise
   `LATEST_SCHEMA_VERSION`. Never edit a step that has shipped, including the baseline:
   a released database has exactly the tables that step created, so a table added to an
   old step is missing from every existing database.
2. Make the step idempotent (`CREATE TABLE IF NOT EXISTS`, add a column only when absent)
   so an interrupted migration can be retried.
3. Test it against a literal copy of the previous release's DDL, as
   `SHIPPED_SCHEMA_4` does in the [resilience tests](../../tests/test_runtime_resilience.py),
   not against the code under test, which would hide a missing table. Assert that the
   migrated schema equals the schema of a fresh database.
4. For a high-risk change, create state with the released code (for example from
   `git archive HEAD src packages` extracted to a temporary folder) and open it with
   the new code.

## Validate your change

Use the existing environment and run the smallest relevant tests first. From
the repository root, for example:

```powershell
uv run --extra dev pytest --no-cov tests\test_discovery.py tests\test_source_adapters.py
uv run --extra dev pytest --no-cov tests\test_multisource_application.py
```

Select tests for the changed layer; include an affected end-to-end workflow.
For example, [acceptance tests](../../tests/test_acceptance.py) check generated
artifact and deployment contracts using local or mocked behavior. They do not
replace semantic parity testing or a separately authorized live Fabric run.
If you change a compiler or the artifact writer, also run
[the sample-estate digest](../../tests/test_golden_digest.py). It hashes a fresh
write of the synthetic sample estate and does not overwrite
`generated-fabric-workflows/`. Refresh the fixture only for an intentional output
change:

```powershell
uv run --extra dev python tests\test_golden_digest.py
```

Before committing, run the repository validation gate from the root:

```powershell
uv run --extra dev ruff check src packages tests examples
uv run --extra dev mypy
uv run --extra dev pytest --cov-fail-under=80
```

If you changed plugin discovery, registration, or the example plugins, also prove the
packaging path. CI does this in the `plugin-entry-points` job; to repeat it without
touching your working environment, use a throwaway one:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$env:TEMP\accelerator-plugins-env"
uv sync --extra dev --locked
uv pip install --no-deps --python "$env:UV_PROJECT_ENVIRONMENT\Scripts\python.exe" `
  .\examples\plugins\synthetic-ssis .\examples\plugins\synthetic-databricks
$env:ACCELERATOR_REQUIRE_INSTALLED_PLUGINS = "1"
uv run --no-sync pytest --no-cov tests\test_installed_plugins.py
uv run --no-sync tool plugins
```

`tool plugins` exits with code 1 when an installed plugin fails to load. Put new tests
in a focused module for the area you changed rather than in `tests\test_delivery.py`;
`tests\conftest.py` already clears the `ACCELERATOR_*` settings for every test.

```powershell
npm run lint
npm test
npm run build
```

For Fabric-native analyst app changes, also run `npm run lint` and `npm test`
from `apps\etl-migration-assessment-app`; follow its
[visual validation guidance](../../apps/etl-migration-assessment-app/AGENTS.md)
when changing visuals. Use the configured npm registry.

Report the exact checks and results in the pull request. If an environment,
credential, or permission prevents a check, state what was not verified. Do not
dispatch CI workflows or deploy to a workspace without authorization.

## Pull request checklist

* Link the issue and explain the user-visible change and its boundaries.
* Include synthetic regression tests for the behavior and relevant failure
  cases.
* Confirm unsupported constructs remain explicit and non-deployable.
* Check backward compatibility, versions, cache behavior, and redaction where
  affected.
* Update related documentation and `toc.yml` when adding a documentation page.
* Record validation results and any remaining manual parity or deployment
  checks.
