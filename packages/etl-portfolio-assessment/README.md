# etl-portfolio-assessment

Target-neutral ETL portfolio assessment engine over `etl-migration-core`. Computes asset inventory, intrinsic complexity scores, dependency analysis, base effort estimates, neutral workload profiles, and bounded redacted evidence without coupling to any destination platform.

## Installation

```bash
pip install etl-portfolio-assessment
```

Requires Python 3.13 or later.

## Quickstart

```bash
etl-assess preview ./alteryx-workflows
etl-assess assess ./alteryx-workflows
etl-assess evidence ./alteryx-workflows
```

```python
from pathlib import Path
from etl_portfolio_assessment.service.application import PortfolioAssessmentApplication

result = PortfolioAssessmentApplication().assess_neutral(Path("alteryx-workflows"))
print(result.workflow_count, result.failed_count)
```

