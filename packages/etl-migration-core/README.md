# etl-migration-core

Canonical ETL intermediate representation (`EtlPackage`, `EtlAsset`, `EtlGraph`), secure file/archive discovery, built-in source adapters (Alteryx Designer, Informatica PowerCenter, Informatica IDMC), and Service Provider Interface (SPI) contracts for pluggable source and target providers.

## Installation

```bash
pip install etl-migration-core
```

Requires Python 3.13 or later. Runtime dependencies are `pydantic` and `defusedxml`.

## Quickstart

```python
from pathlib import Path
from etl_migration_core.intake.discovery import DiscoveryService
from etl_migration_core.sources.defaults import create_default_registry

summary = DiscoveryService().discover(Path("alteryx-workflows"))
registry = create_default_registry()
first = summary.workflows[0]
detected = registry.detect(Path(first.source_path), first.display_path)
package = registry.parse(Path(first.source_path), detected.match)
print(package.ir_version, len(package.assets))
```

