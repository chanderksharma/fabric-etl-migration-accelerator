## Summary

<!-- Describe what this pull request changes and why. -->

Fixes #<!-- GitHub Issue number -->

## Key Changes

-
-

## Validation Performed

- [ ] `uv run --extra dev ruff check src tests` and `uv run --extra dev mypy` pass
- [ ] `uv run --extra dev pytest --cov-fail-under=80` passes
- [ ] `npm run lint && npm test && npm run build` pass in `apps/web`
- [ ] Documentation (`README.md`, `docs/`, `toc.yml`) updated if behavior changed

## Chrysalis & Security Hygiene Checklist

- [ ] Zero customer workflows (`.yxmd`, `.xml`, `.zip`), customer names, or engagement identifiers included
- [ ] Zero Entra tenant IDs, subscription IDs, Fabric workspace GUIDs, local user paths, or credentials committed
- [ ] New third-party dependencies reviewed against `NOTICE.md` and `pip-audit` / `npm audit`
