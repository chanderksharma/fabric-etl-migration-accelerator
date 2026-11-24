"""Tests for deterministic workflow assessment."""

from pathlib import Path

from etl_target_fabric.assessment.workflow import assess_workflow


def test_assessment_inventories_tools_and_recommends_dataflow(tmp_path: Path) -> None:
    workflow = tmp_path / "orders.yxmd"
    workflow.write_text(
        """
        <AlteryxDocument>
          <Nodes>
            <Node ToolID="1">
              <GuiSettings Plugin="AlteryxBasePluginsGui.InputData.InputData" />
            </Node>
            <Node ToolID="2">
              <GuiSettings Plugin="AlteryxBasePluginsGui.Filter.Filter" />
            </Node>
          </Nodes>
          <Connections>
            <Connection>
              <Origin ToolID="1" /><Destination ToolID="2" />
            </Connection>
          </Connections>
        </AlteryxDocument>
        """,
        encoding="utf-8",
    )

    result = assess_workflow(workflow)

    assert result.tool_count == 2
    assert result.connection_count == 1
    assert result.recommended_target == "Dataflow Gen2"
    assert result.complexity_score == 3
    assert result.migration_wave == "Wave 1"
    assert result.estimated_effort_days == 0.5


def test_unknown_tool_requires_manual_rework(tmp_path: Path) -> None:
    workflow = tmp_path / "custom.yxmd"
    workflow.write_text(
        """
        <AlteryxDocument>
          <Nodes>
            <Node ToolID="1"><GuiSettings Plugin="Company.CustomTool" /></Node>
          </Nodes>
        </AlteryxDocument>
        """,
        encoding="utf-8",
    )

    result = assess_workflow(workflow)

    assert result.recommended_target == "Manual rework"
    assert result.unsupported_tools == ("Custom",)
    assert result.migration_wave == "Redesign"
    assert result.estimated_effort_days == 1.5


def test_alteryx_effort_is_capped_at_twenty_one_days(tmp_path: Path) -> None:
    workflow = tmp_path / "large-custom.yxmd"
    nodes = "".join(
        f'<Node ToolID="{index}"><GuiSettings Plugin="Company.Custom{index}" /></Node>'
        for index in range(30)
    )
    workflow.write_text(
        f"<AlteryxDocument><Nodes>{nodes}</Nodes></AlteryxDocument>",
        encoding="utf-8",
    )

    result = assess_workflow(workflow)

    assert result.estimated_effort_days == 21.0


def test_download_workflow_recommends_fabric_pipeline(tmp_path: Path) -> None:
    workflow = tmp_path / "download.yxmd"
    workflow.write_text(
        """
        <AlteryxDocument>
          <Nodes>
            <Node ToolID="1"><GuiSettings Plugin="AlteryxBasePluginsGui.Download.Download" /></Node>
          </Nodes>
        </AlteryxDocument>
        """,
        encoding="utf-8",
    )

    result = assess_workflow(workflow)

    assert result.recommended_target == "Fabric Pipeline"
    assert result.target_components == ("Fabric Pipeline",)


def test_dataflow_and_notebook_tools_recommend_mixed_solution(tmp_path: Path) -> None:
    workflow = tmp_path / "mixed.yxmd"
    workflow.write_text(
        """
        <AlteryxDocument>
          <Nodes>
            <Node ToolID="1"><GuiSettings Plugin="AlteryxBasePluginsGui.Filter.Filter" /></Node>
            <Node ToolID="2">
              <GuiSettings Plugin="AlteryxBasePluginsGui.MultiRowFormula.MultiRowFormula" />
            </Node>
          </Nodes>
        </AlteryxDocument>
        """,
        encoding="utf-8",
    )

    result = assess_workflow(workflow)

    assert result.recommended_target == "Mixed Fabric solution"
    assert result.target_components == ("Dataflow Gen2", "Fabric Notebook")


def test_all_component_signals_recommend_mixed_solution(tmp_path: Path) -> None:
    workflow = tmp_path / "mixed-all.yxmd"
    workflow.write_text(
        """
        <AlteryxDocument>
          <Nodes>
            <Node ToolID="1"><GuiSettings Plugin="AlteryxBasePluginsGui.Filter.Filter" /></Node>
            <Node ToolID="2"><GuiSettings Plugin="AlteryxBasePluginsGui.Python.Python" /></Node>
            <Node ToolID="3"><GuiSettings Plugin="AlteryxBasePluginsGui.Download.Download" /></Node>
          </Nodes>
        </AlteryxDocument>
        """,
        encoding="utf-8",
    )

    result = assess_workflow(workflow)

    assert result.recommended_target == "Mixed Fabric solution"
    assert result.target_components == (
        "Dataflow Gen2",
        "Fabric Notebook",
        "Fabric Pipeline",
    )
    assert result.migration_wave == "Wave 2"


def test_wave_progression_orders_low_medium_high_mixed_and_redesign() -> None:
    from etl_target_fabric.assessment.support_matrix import complexity_band, migration_wave

    assert complexity_band(19) == "Low"
    assert complexity_band(20) == "Medium"
    assert complexity_band(59) == "Medium"
    assert complexity_band(60) == "High"

    assert migration_wave("Dataflow Gen2", "Low") == "Wave 1"
    assert migration_wave("Dataflow Gen2", "Medium") == "Pilot"
    assert migration_wave("Fabric Notebook", "Medium") == "Pilot"
    assert migration_wave("Dataflow Gen2", "High") == "Wave 2"
    assert migration_wave("Mixed Fabric solution", "Low") == "Wave 2"
    assert migration_wave("Manual rework", "Low") == "Redesign"


def test_confirm_assessment_recomputes_wave_when_target_narrows() -> None:
    from etl_migration_core.contracts.spi import TargetEvaluation
    from etl_target_fabric.assessment.schemas import WorkflowAssessmentResponse
    from etl_target_fabric.evaluation.native_route import confirm_assessment

    static = WorkflowAssessmentResponse(
        path="orders.yxmd",
        tool_count=10,
        connection_count=9,
        tools=[],
        complexity_score=24,
        complexity_band="Medium",
        recommended_target="Mixed Fabric solution",
        target_components=["Dataflow Gen2", "Fabric Notebook"],
        recommendation_reason="Static mixed",
        unsupported_tools=[],
        migration_wave="Wave 2",
        estimated_effort_days=1.5,
        registry_version="2026.11.3",
        rules_version="1.5.0",
    )
    evaluation = TargetEvaluation(
        platform_id="fabric",
        implemented=True,
        recommended_target="Dataflow Gen2",
        target_components=("Dataflow Gen2",),
        recommendation_reason="Confirmed Dataflow Gen2",
        estimated_effort_days=0.6,
    )

    confirmed = confirm_assessment(static, evaluation)
    assert confirmed.recommended_target == "Dataflow Gen2"
    assert confirmed.migration_wave == "Pilot"
