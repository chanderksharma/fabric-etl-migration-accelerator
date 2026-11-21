"""Target-neutral ETL portfolio assessment engine and evidence extraction."""

from etl_portfolio_assessment.assessment.engine import (
    NEUTRAL_ASSESSMENT_VERSION,
    NeutralAssetAssessment,
    NeutralComponentItem,
    assess_package_neutral,
    classify_neutral_operation,
)
from etl_portfolio_assessment.assessment.workload_profile import extract_workload_profile
from etl_portfolio_assessment.service.application import PortfolioAssessmentApplication

__version__ = "1.0.0"

__all__ = [
    "NEUTRAL_ASSESSMENT_VERSION",
    "NeutralAssetAssessment",
    "NeutralComponentItem",
    "PortfolioAssessmentApplication",
    "__version__",
    "assess_package_neutral",
    "classify_neutral_operation",
    "extract_workload_profile",
]
