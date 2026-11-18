"""Acceptance checks for generated components and deployment contracts."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
ARTIFACT_ROOT = ROOT / "generated-fabric-workflows"


def test_deployment_plan_references_only_native_component_envelopes() -> None:
    plan = json.loads((ARTIFACT_ROOT / "deployment-plan.json").read_text(encoding="utf-8"))
    assert plan["workflow_count"] == len(plan["workflows"])
    assert plan["native_ready_count"] == sum(
        workflow["status"] == "native_ready" for workflow in plan["workflows"]
    )
    assert plan["compiler_required_count"] == sum(
        workflow["status"] == "compiler_required" for workflow in plan["workflows"]
    )
    for workflow in plan["workflows"]:
        folder = ARTIFACT_ROOT.joinpath(*workflow["artifact_path"].split("/"))
        if workflow["status"] == "native_ready":
            if workflow["pipeline_required"]:
                assert len(workflow["selected_components"]) >= 2
                assert any(
                    component["type"] == "DataPipeline"
                    for component in workflow["selected_components"]
                )
            else:
                assert len(workflow["selected_components"]) == 1
            for component in workflow["selected_components"]:
                for name in component["definition_files"]:
                    assert (folder / name).is_file()
        else:
            assert workflow["selected_components"] == []
            assert not list(folder.glob("*-create-item.json"))
    reconciliation = (
        ARTIFACT_ROOT
        / "alteryx-workflows"
        / "11_multi_container_reconciliation"
    )
    metadata = json.loads(
        (reconciliation / "dataflow-queryMetadata.json").read_text(encoding="utf-8")
    )
    assert [group["name"] for group in metadata["queryGroups"]] == [
        "00 Source Files",
        "01 Ledger Alpha and Beta",
        "02 Reference Enrichment",
        "03 Settlement Reconciliation",
        "04 Final Outputs",
        "05 Destinations",
    ]
    group_ids = {group["id"] for group in metadata["queryGroups"]}
    assert len(metadata["queriesMetadata"]) == 30
    assert metadata["computeEngineSettings"] == {"allowFastCopy": False}
    assert all(
        query["queryGroupId"] in group_ids
        for name, query in metadata["queriesMetadata"].items()
        if name != "SourceBindings"
    )
    assert all(
        query["loadEnabled"] is False
        for query in metadata["queriesMetadata"].values()
    )
    informatica_metadata = json.loads(
        (
            ARTIFACT_ROOT
            / "informatica-powercenter"
            / "wf_STG_Ledger_Validation"
            / "dataflow-queryMetadata.json"
        ).read_text(encoding="utf-8")
    )
    assert informatica_metadata["computeEngineSettings"] == {"allowFastCopy": False}
    assert all(
        query["loadEnabled"] is False
        for query in informatica_metadata["queriesMetadata"].values()
    )


def test_deployment_workflow_is_dev_only_and_idempotent() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy-fabric-artifacts.yml").read_text(
        encoding="utf-8"
    )
    assert "name: dev" in workflow
    assert "default: Update" in workflow
    assert "- Bundle" in workflow
    assert "- DataPipeline" in workflow
    assert "runs-on: [self-hosted, Windows, X64]" in workflow
    assert "FABRIC_SYNC_DEVELOPMENT_TO_GIT == 'true'" in workflow
    assert "Invoke-FabricAlm.ps1" in workflow
    assert "SyncDevelopmentToGit" in workflow
    assert "production" not in workflow.casefold()


def test_fabric_alm_promotion_is_manual_and_environment_gated() -> None:
    workflow = (ROOT / ".github" / "workflows" / "promote-fabric-alm.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "push:" not in workflow
    assert "pull_request:" not in workflow
    assert "target_stage:" in workflow
    assert "- Test" in workflow
    assert "- Production" in workflow
    assert "name: ${{ inputs.target_stage == 'Production' && 'prod' || 'test' }}" in workflow
    assert "FABRIC_DEPLOYMENT_PIPELINE_ID" in workflow
    assert "FABRIC_VARIABLE_LIBRARY_NAME" in workflow
    assert "FABRIC_ACTIVE_VALUE_SET_NAME" in workflow
    assert "Invoke-FabricAlm.ps1" in workflow
    assert "Operation = 'Promote'" in workflow


def test_fabric_alm_script_fails_closed_and_uses_native_alm_apis() -> None:
    script = (ROOT / "scripts" / "Invoke-FabricAlm.ps1").read_text(encoding="utf-8")
    module = (ROOT / "scripts" / "FabricApi.psm1").read_text(encoding="utf-8")
    deployment_script = (ROOT / "scripts" / "Deploy-FabricArtifacts.ps1").read_text(
        encoding="utf-8"
    )

    assert "/git/status" in script
    assert "/git/commitToGit" in script
    assert "/deploymentPipelines/$PipelineId/stages" in script
    assert "/deploymentPipelines/$PipelineId/deploy" in script
    assert "/variableLibraries/$LibraryId" in script
    assert "remote changes; update or reconcile" in script
    assert "contains conflicts; reconcile" in script
    assert "adjacent forward Deployment Pipeline stages" in script
    assert "git-integration-operations-cli" in script
    assert "deployment-pipelines-authoring-cli" in script
    assert "variable-library-cli" in script
    assert "?beta=true" in script
    assert "'x-ms-fabric-skill'" in module
    assert "'Get', 'Post', 'Patch'" in module
    assert "'x-ms-operation-id'" in module
    assert "Import-Module (Join-Path $PSScriptRoot 'FabricApi.psm1') -Force" in (
        deployment_script
    )


def test_gitlab_pipeline_is_dispatch_only_and_uses_fabric_deployment_script() -> None:
    pipeline = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")

    assert '$CI_PIPELINE_SOURCE == "api"' in pipeline
    assert '$CI_PIPELINE_SOURCE == "web"' in pipeline
    assert "name: 'Deploy $TARGET $WORKFLOW_FILTER ($DEPLOYMENT_ID)'" in pipeline
    assert "scripts/Deploy-FabricArtifacts.ps1" in pipeline
    assert "fabric-deploy-windows" in pipeline
    assert "FABRIC_WORKSPACE_ID" in pipeline
    assert "DEPLOYMENT_ID" in pipeline
    assert "description: Fabric item type to deploy" in pipeline
    assert (
        'options: ["Both", "Bundle", "Dataflow", "Notebook", "DataPipeline"]'
        in pipeline
    )
    assert 'options: ["Fail", "Skip", "Update"]' in pipeline
    assert 'options: ["false", "true"]' in pipeline
    assert "WORKFLOW_FILTER" in pipeline
    assert "CONFLICT_BEHAVIOR" in pipeline
    assert "DRY_RUN" in pipeline
    assert "unsupported TARGET" in pipeline
    assert "unsupported CONFLICT_BEHAVIOR" in pipeline
    assert "DRY_RUN must be true or false" in pipeline
    assert "production" not in pipeline.casefold()


def test_deployment_script_uses_saved_queries_and_respects_binding_readiness() -> None:
    script = (ROOT / "scripts" / "Deploy-FabricArtifacts.ps1").read_text(
        encoding="utf-8"
    )
    assert "ValidationQueryNames" in script
    assert "loaded_queries" in script
    assert "RuntimeReady" in script
    assert "BindingsRequired" in script
    assert "-SkipHttpErrorCheck" in script
    assert "-QueryName $Candidate.DisplayName" not in script
    assert "pipeline-create-item.json" in script
    assert "{{DATAFLOW_ITEM_ID}}" in script
    assert "{{NOTEBOOK_ITEM_ID}}" in script
    assert "'dataPipelines'" in script
    assert "Pipeline dependencies were not deployed" in script
