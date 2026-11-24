"""Capacity estimation persistence and computation for completed runs."""

from __future__ import annotations

from accelerator.runtime.models import Run
from accelerator.runtime.store import RunStore
from etl_target_fabric.capacity.model import (
    CapacityPortfolioEstimate,
    CapacitySettings,
    CapacityUpdate,
    CapacityWorkflowInput,
    capacity_csv,
    estimate_capacity,
)


class CapacityService:
    """Persist mutable capacity inputs and compute deterministic Fabric capacity estimates."""

    def __init__(self, store: RunStore) -> None:
        self._store = store

    def estimate_for_run(self, identity: str, run: Run) -> CapacityPortfolioEstimate:
        """Compute the portfolio capacity estimate for a completed run."""
        if run.status != "completed" or run.result is None:
            raise ValueError("Complete an assessment before estimating capacity")
        defaults = {
            assessment.path: CapacityWorkflowInput(workflow_path=assessment.path)
            for assessment in run.result.assessments
            if assessment.capacity_profile is not None
        }
        with self._store.connection() as connection:
            settings_row = connection.execute(
                "SELECT settings_json FROM capacity_settings WHERE run_id=?",
                (identity,),
            ).fetchone()
            input_rows = connection.execute(
                "SELECT workflow_path,input_json FROM capacity_inputs WHERE run_id=?",
                (identity,),
            ).fetchall()
            if settings_row is None:
                settings = CapacitySettings()
                connection.execute(
                    "INSERT INTO capacity_settings VALUES (?,?)",
                    (identity, settings.model_dump_json()),
                )
            else:
                settings = CapacitySettings.model_validate_json(settings_row["settings_json"])
            persisted = {
                row["workflow_path"]: CapacityWorkflowInput.model_validate_json(row["input_json"])
                for row in input_rows
            }
            missing_rows = [
                (identity, workflow_path, workflow_input.model_dump_json())
                for workflow_path, workflow_input in defaults.items()
                if workflow_path not in persisted
            ]
            if missing_rows:
                connection.executemany(
                    "INSERT INTO capacity_inputs VALUES (?,?,?)",
                    missing_rows,
                )
        return estimate_capacity(
            run.result.assessments,
            {
                path: persisted.get(path, workflow_input)
                for path, workflow_input in defaults.items()
            },
            settings,
        )

    def update(
        self, identity: str, run: Run, update: CapacityUpdate
    ) -> CapacityPortfolioEstimate:
        """Persist updated operational inputs/settings and recompute the estimate."""
        if run.status != "completed" or run.result is None:
            raise ValueError("Complete an assessment before estimating capacity")
        known_paths = {
            assessment.path
            for assessment in run.result.assessments
            if assessment.capacity_profile is not None
        }
        unknown = sorted(
            workflow.workflow_path
            for workflow in update.inputs
            if workflow.workflow_path not in known_paths
        )
        if unknown:
            raise KeyError(f"Unknown capacity workflow: {unknown[0]}")
        with self._store.connection() as connection:
            if update.settings is not None:
                connection.execute(
                    """INSERT INTO capacity_settings VALUES (?,?)
                    ON CONFLICT(run_id) DO UPDATE SET settings_json=excluded.settings_json""",
                    (identity, update.settings.model_dump_json()),
                )
            if update.inputs:
                connection.executemany(
                    """INSERT INTO capacity_inputs VALUES (?,?,?)
                    ON CONFLICT(run_id,workflow_path)
                    DO UPDATE SET input_json=excluded.input_json""",
                    [
                        (identity, workflow.workflow_path, workflow.model_dump_json())
                        for workflow in update.inputs
                    ],
                )
        return self.estimate_for_run(identity, run)

    @staticmethod
    def to_csv(estimate: CapacityPortfolioEstimate) -> str:
        """Export one capacity estimate as CSV."""
        return capacity_csv(estimate)
