"""Acceptance checks for generated components and deployment contracts."""

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
ARTIFACT_ROOT = ROOT / "generated-fabric-workflows"


@pytest.mark.parametrize(
    ("client_secret", "federated_token", "expected_assertion"),
    [
        ("synthetic-client-secret", "", None),
        ("", "", "synthetic-github-assertion"),
        ("   ", "", "synthetic-github-assertion"),
        ("synthetic-client-secret", "synthetic-explicit-assertion", "synthetic-explicit-assertion"),
    ],
    ids=["client-secret", "github-oidc", "blank-client-secret", "explicit-federation"],
)
def test_fabric_authentication_honors_explicit_credentials(
    client_secret: str, federated_token: str, expected_assertion: str | None
) -> None:
    executable = shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell 7 is required to exercise the Fabric authentication module")
    script = r"""
$ErrorActionPreference = 'Stop'
$global:Requests = @()
function global:Invoke-RestMethod {
    param($Method, $Uri, $Headers, $ContentType, $Body)
    $global:Requests += [pscustomobject]@{
        method = $Method
        uri = $Uri
        body = $Body
    }
    if ($Method -eq 'Get') {
        return @{ value = 'synthetic-github-assertion' }
    }
    return @{ access_token = 'synthetic-fabric-token' }
}
Import-Module (Join-Path $PWD 'scripts\FabricApi.psm1') -Force
$Token = Get-FabricAccessToken
@{ token = $Token; requests = @($global:Requests) } | ConvertTo-Json -Depth 8 -Compress
"""
    environment = os.environ | {
        "AZURE_CLIENT_ID": "synthetic-client-id",
        "AZURE_TENANT_ID": "synthetic-tenant-id",
        "AZURE_CLIENT_SECRET": client_secret,
        "AZURE_FEDERATED_TOKEN": federated_token,
        "AZURE_FEDERATED_TOKEN_FILE": "",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://oidc.example.invalid/token?api-version=2.0",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "synthetic-runner-token",
    }
    result = subprocess.run(
        [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    response = json.loads(result.stdout)
    assert response["token"] == "synthetic-fabric-token"
    requests = response["requests"]
    automatic_oidc = not client_secret.strip() and not federated_token
    assert len(requests) == (2 if automatic_oidc else 1)
    if automatic_oidc:
        assert requests[0]["method"] == "Get"
        assert requests[0]["uri"].endswith("&audience=api://AzureADTokenExchange")
    assert requests[-1]["method"] == "Post"
    body = requests[-1]["body"]
    if expected_assertion is None:
        assert body["client_secret"] == client_secret
        assert "client_assertion" not in body
    else:
        assert body["client_assertion"] == expected_assertion
        assert "client_secret" not in body


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
    assert "INPUT_ACTIVE_VALUE_SET_NAME" in workflow
    assert "Invoke-FabricAlm.ps1" in workflow
    assert "Operation = 'Promote'" in workflow


@pytest.mark.parametrize("target_stage", ["Test", "Production"])
@pytest.mark.parametrize("library_name", ["", "synthetic-library"], ids=["no-library", "library"])
def test_fabric_alm_workflow_handles_optional_variable_library(
    target_stage: str, library_name: str
) -> None:
    executable = shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell 7 is required to exercise the promotion workflow")
    workflow = (ROOT / ".github" / "workflows" / "promote-fabric-alm.yml").read_text(
        encoding="utf-8"
    )
    value_set_variable = next(
        line.strip().split(":", 1)[0]
        for line in workflow.splitlines()
        if "vars.FABRIC_PROD_VALUE_SET_NAME" in line
    )
    run_script = textwrap.dedent(workflow.partition("        run: |\n")[2])
    assert run_script.count("@Parameters") == 1
    run_script = run_script.replace("@Parameters", "@Parameters -DryRun")
    run_script = run_script.replace("${{ inputs.use_preview_deployment_plan }}", "false")
    source_stage = "Test" if target_stage == "Production" else "Development"
    environment = os.environ | {
        "AZURE_CLIENT_ID": "",
        "AZURE_TENANT_ID": "",
        "AZURE_CLIENT_SECRET": "",
        "GITHUB_STEP_SUMMARY": "",
        "FABRIC_DEPLOYMENT_PIPELINE_ID": "00000000-0000-0000-0000-000000000001",
        "FABRIC_SOURCE_STAGE_NAME": source_stage,
        "FABRIC_TARGET_STAGE_NAME": target_stage,
        "FABRIC_VARIABLE_LIBRARY_NAME": library_name,
        "FABRIC_ACTIVE_VALUE_SET_NAME": "",
        "FABRIC_DEPLOYMENT_PLAN_ID": "",
        "FABRIC_DEPLOYMENT_NOTE": "Synthetic promotion acceptance check",
    }
    environment[value_set_variable] = "prod" if target_stage == "Production" else "test"
    result = subprocess.run(
        [
            executable,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$ErrorActionPreference = 'Stop'\n" + run_script,
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    response = json.loads(result.stdout)
    assert response["Status"] == "WouldPromote"
    assert response["SourceStage"] == source_stage
    assert response["TargetStage"] == target_stage


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
