# Security Policy

## Scope and Classification

This Microsoft Fabric ETL Migration Accelerator is an internal Microsoft IP asset (`Internal Only = Yes` in Chrysalis). Never commit customer source workflows, tenant/workspace identifiers, connection strings, or service-principal secrets to this repository.

## Supported Versions

| Version | Supported |
| ------- | --------- |
| `1.0.x` | Yes       |
| `< 1.0` | No        |

## Security Controls

- **Untrusted Input Isolation**: XML parsing uses `defusedxml` with external entity expansion disabled, bounded nesting depth (64), element count caps (100,000), and strict archive-bomb / path-traversal budgets.
- **Loopback & Origin Enforcement**: Local analyst service binds exclusively to `127.0.0.1` with trusted-host validation and CSRF/session tokens on mutating endpoints.
- **Secretless CI Deployment**: `scripts/Deploy-FabricArtifacts.ps1` and `.github/workflows/deploy-fabric-artifacts.yml` support Microsoft Entra Workload Identity Federation (OIDC) by default (`AZURE_CLIENT_SECRET` is optional fallback only).
- **Automated SDL Checks**: GitHub Actions CI enforces CodeQL static analysis (`python` and `javascript-typescript`), `pip-audit --strict`, `npm audit --audit-level=high`, and Dependabot version updates.

## Reporting a Vulnerability

Do **not** open public issues containing exploit details, credentials, or customer information.

1. Report suspected vulnerabilities privately via **GitHub Security Advisories** on the repository, or contact the listed repository maintainers in `CODEOWNERS` / Chrysalis Asset Owners.
2. For Microsoft-wide security incidents or credential exposure, follow Microsoft Security Response Center (MSRC) and internal incident escalation procedures immediately.
