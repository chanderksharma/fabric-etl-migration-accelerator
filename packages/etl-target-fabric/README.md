# etl-target-fabric

Microsoft Fabric target-platform provider plugin for `etl-migration-core`. Provides compiler-grounded Fabric target-fit evaluation, F-SKU capacity sizing, Dataflow Gen2 (Power Query M), PySpark Notebook, and Data Pipeline code generation, artifact bundle emission, and dry-run planning.

## Installation

```bash
pip install etl-target-fabric
```

Requires Python 3.13 or later. Installing this package automatically registers the `"fabric"` provider under the `etl_migration.targets` entry-point group.

## Quickstart

```bash
etl-fabric evaluate ./alteryx-workflows/sample_alteryx_workflow.yxmd
etl-fabric compile ./alteryx-workflows/sample_alteryx_workflow.yxmd --target dataflow
```

```python
from pathlib import Path
from etl_target_fabric.compilers.alteryx import generate_candidate

candidate = generate_candidate(Path("alteryx-workflows/sample_alteryx_workflow.yxmd"), "dataflow")
print(candidate.validation_state, candidate.deployable)
```

## Assessment, fit, and generation

Assessment, fit, and generation are separate. `etl_target_fabric.assessment` is
static and imports no compiler. `etl_target_fabric.evaluation` confirms Fabric
routing with the compilers, and `etl_target_fabric.compilers` generates
definitions.

```python
from pathlib import Path
from etl_target_fabric.application import FabricAssessmentApplication

application = FabricAssessmentApplication()
static = application.assess(Path("alteryx-workflows"))                        # no compiler runs
confirmed = application.assess(Path("alteryx-workflows"), route_native=True)  # compilers confirm routes
```

