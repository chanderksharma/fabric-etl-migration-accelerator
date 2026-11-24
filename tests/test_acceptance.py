"""Acceptance checks for generated components and deployment contracts."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
ARTIFACT_ROOT = ROOT / "generated-fabric-workflows"


def test_ci_revision_check_precedes_fabric_deployment() -> None:
    github = (ROOT / ".github" / "workflows" / "deploy-fabric-artifacts.yml").read_text(
        encoding="utf-8"
    )
    gitlab = (ROOT / ".gitlab" / "ci" / "deploy-fabric-artifacts.yml").read_text(
        encoding="utf-8"
    )
    assert github.index("scripts/Assert-DeploymentRevision.ps1") < github.index(
        "scripts/Deploy-FabricArtifacts.ps1"
    )
    assert gitlab.index("scripts/Assert-DeploymentRevision.ps1") < gitlab.index(
        "scripts/Deploy-FabricArtifacts.ps1"
    )
    assert github.index("scripts/Assert-DeploymentPublication.ps1") < github.index(
        "scripts/Deploy-FabricArtifacts.ps1"
    )
    assert gitlab.index("scripts/Assert-DeploymentPublication.ps1") < gitlab.index(
        "scripts/Deploy-FabricArtifacts.ps1"
    )
    assert "if ($LASTEXITCODE -ne 0)" in gitlab


def test_publication_verifier_rejects_modified_and_extra_files(tmp_path: Path) -> None:
    executable = shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell 7 is required to exercise publication verification")
    run_id = "1" * 32
    digest = "2" * 64
    relative_root = f"published-fabric-workflows/{run_id}/{digest}"
    root = tmp_path / "published-fabric-workflows" / run_id / digest
    artifact = root / "orders" / "dataflow-create-item.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"synthetic-definition")
    entry = {
        "path": "orders/dataflow-create-item.json",
        "size_bytes": len(artifact.read_bytes()),
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }
    manifest = {
        "version": 1,
        "run_id": run_id,
        "files": [entry],
    }
    manifest_path = root / "publication-manifest.json"
    manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    def verify(expected_hash: str = manifest_hash) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
                str(ROOT / "scripts" / "Assert-DeploymentPublication.ps1"),
                "-ArtifactRoot", relative_root, "-ExpectedManifestSha256", expected_hash,
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    accepted = verify()
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert verify("0" * 64).returncode != 0
    artifact.write_bytes(b"synthetic-definitioN")
    assert verify().returncode != 0
    artifact.write_bytes(b"synthetic-definition")
    extra = root / "unexpected.json"
    extra.write_text("extra", encoding="utf-8")
    assert verify().returncode != 0
    extra.unlink()
    artifact.unlink()
    assert verify().returncode != 0
    artifact.write_bytes(b"synthetic-definition")
    entry["path"] = "../outside.json"
    manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())
    assert verify(hashlib.sha256(manifest_path.read_bytes()).hexdigest()).returncode != 0
    entry["path"] = "orders/dataflow-create-item.json"
    manifest["files"] = [entry, entry.copy() | {"path": "ORDERS/dataflow-create-item.json"}]
    manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())
    assert verify(hashlib.sha256(manifest_path.read_bytes()).hexdigest()).returncode != 0


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
    assert "vars.DEPLOY_RUNNER_LABELS" in workflow
    assert '"self-hosted", "Windows", "X64"' in workflow
    assert "FABRIC_SYNC_DEVELOPMENT_TO_GIT == 'true'" in workflow
    assert "Invoke-FabricAlm.ps1" in workflow
    assert "SyncDevelopmentToGit" in workflow
    assert "production" not in workflow.casefold()


@pytest.mark.parametrize(
    "workflow_name",
    [
        "deploy-fabric-artifacts.yml",
        "create-fabric-deployment-pipeline.yml",
        "promote-fabric-alm.yml",
    ],
)
def test_deployment_workflows_take_their_runner_from_one_variable(workflow_name: str) -> None:
    workflow = (ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")

    assert "runs-on: [" not in workflow
    assert workflow.count("runs-on:") == workflow.count("vars.DEPLOY_RUNNER_LABELS")


@pytest.mark.parametrize(
    "workflow_filter",
    ["02_low_west_sample", r"alteryx-workflows\02_low_west_sample", "alteryx-workflows/02_*"],
)
def test_deployment_script_matches_workflow_name_or_relative_path(
    workflow_filter: str,
) -> None:
    executable = shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell 7 is required to exercise deployment filtering")
    source = ARTIFACT_ROOT / "alteryx-workflows" / "02_low_west_sample"
    state_root = ROOT / ".accelerator"
    state_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="filter-test-", dir=state_root) as directory:
        artifact_root = Path(directory) / "artifacts"
        destination = artifact_root / "alteryx-workflows" / source.name
        shutil.copytree(source, destination)

        result = subprocess.run(
            [
                executable,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(ROOT / "scripts" / "Deploy-FabricArtifacts.ps1"),
                "-ArtifactRoot",
                str(artifact_root),
                "-Target",
                "Dataflow",
                "-WorkflowFilter",
                workflow_filter,
                "-DryRun",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )

    response = json.loads(result.stdout)
    assert response["DisplayName"] == "02_low_west_sample"
    assert response["Target"] == "Dataflow"
    assert response["Action"] == "WouldDeploy"


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
    run_script = textwrap.dedent(workflow.rpartition("        run: |\n")[2])
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
        "INPUT_PROMOTION_SCOPE": "All",
        "INPUT_SELECTED_ITEMS": "[]",
        "INPUT_DEPENDENCIES_REVIEWED": "false",
        "INPUT_PREVIEW_DEPLOYMENT_PLAN": "false",
        "INPUT_REVIEWED_PLAN": "{}",
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
    assert "/deploymentPipelines/$($PromotionPlan.PipelineId)/deploy" in script
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
    root = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    deploy = (
        ROOT / ".gitlab" / "ci" / "deploy-fabric-artifacts.yml"
    ).read_text(encoding="utf-8")
    create = (
        ROOT / ".gitlab" / "ci" / "create-fabric-deployment-pipeline.yml"
    ).read_text(encoding="utf-8")
    promote = (
        ROOT / ".gitlab" / "ci" / "promote-fabric-alm.yml"
    ).read_text(encoding="utf-8")
    pipeline = "\n".join((root, deploy, create, promote))

    assert '$CI_PIPELINE_SOURCE == "api"' in pipeline
    assert '$CI_PIPELINE_SOURCE == "web"' in pipeline
    assert "name: 'Fabric $FABRIC_OPERATION ($DEPLOYMENT_ID)'" in pipeline
    assert 'options: ["Deploy", "CreatePipeline", "Promote"]' in pipeline
    assert "include:" in root
    assert ".gitlab/ci/deploy-fabric-artifacts.yml" in root
    assert ".gitlab/ci/create-fabric-deployment-pipeline.yml" in root
    assert ".gitlab/ci/promote-fabric-alm.yml" in root
    assert "scripts/Deploy-FabricArtifacts.ps1" in pipeline
    assert "scripts/New-FabricDeploymentPipeline.ps1" in pipeline
    assert "scripts/Invoke-FabricAlm.ps1" in pipeline
    assert "fabric-deploy-windows" in pipeline
    assert "FABRIC_OIDC_TOKEN" in pipeline
    assert "AZURE_FEDERATED_TOKEN" in pipeline
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
    assert "PlanPromotion" in promote
    assert "ReviewedPlanJson" in promote
    assert "promotion-plan.json" in promote
    assert "when: manual" in promote
    assert "PROMOTION_TARGET_ENVIRONMENT: prod" in promote
    assert "PROMOTION_TARGET_ENVIRONMENT: test" in promote
    assert 'if: \'$FABRIC_OPERATION == "CreatePipeline"\'' in create
    assert 'if: \'$FABRIC_OPERATION == "Deploy"\'' in deploy


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


def test_fabric_api_blocks_foreign_lro_origin_and_caps_retry_after() -> None:
    executable = shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell 7 is required to test FabricApi.psm1")
    script = textwrap.dedent(
        """
        $ErrorActionPreference = 'Stop'
        Import-Module (Join-Path $PWD 'scripts\\FabricApi.psm1') -Force
        $script:SeenUris = @()
        $script:SleepCalls = @()
        function global:Start-Sleep { param([int]$Seconds) $script:SleepCalls += $Seconds }
        function global:Invoke-WebRequest {
            param(
                $Method, $Uri, $Headers, $Body,
                $SkipHttpErrorCheck, $MaximumRedirection, $TimeoutSec
            )
            if ($TimeoutSec -ne 60) { throw "Expected TimeoutSec=60, got $TimeoutSec" }
            $script:SeenUris += $Uri
            if ($Uri -like '*/evil-lro') {
                return [pscustomobject]@{
                    StatusCode = 202
                    Headers = @{
                        Location = 'https://evil.example/steal-token'
                        'Retry-After' = '99999'
                    }
                    Content = ''
                }
            }
            if ($Uri -like '*/ok-lro') {
                return [pscustomobject]@{
                    StatusCode = 202
                    Headers = @{
                        Location = '/v1/operations/op-123'
                        'Retry-After' = '99999'
                    }
                    Content = ''
                }
            }
            if ($Uri -eq 'https://api.fabric.microsoft.com/v1/operations/op-123') {
                return [pscustomobject]@{
                    StatusCode = 200
                    Headers = @{}
                    Content = '{"status":"Succeeded"}'
                }
            }
            throw "Unexpected URI: $Uri"
        }

        $rejected = $false
        try {
            Invoke-FabricRequest -Method Post `
                -Uri 'https://api.fabric.microsoft.com/v1/evil-lro' `
                -Token 'secret-tok' -SkillName 'test-skill'
        } catch {
            if ($_.Exception.Message -match 'Refusing to poll Fabric LRO Location outside') {
                $rejected = $true
            } else {
                throw
            }
        }
        if (-not $rejected) { throw 'Foreign LRO Location was not rejected' }
        if ($script:SeenUris -contains 'https://evil.example/steal-token') {
            throw 'Token was forwarded to foreign LRO origin'
        }

        $ok = Invoke-FabricRequest -Method Post `
            -Uri 'https://api.fabric.microsoft.com/v1/ok-lro' `
            -Token 'secret-tok' -SkillName 'test-skill'
        if ($ok.status -ne 'Succeeded') { throw 'Valid same-origin LRO did not succeed' }
        $lastSleep = $script:SleepCalls[-1]
        if ($lastSleep -ne 60) { throw "Expected capped Retry-After=60, got $lastSleep" }
        Write-Output 'FABRIC_API_SECURITY_OK'
        """
    )
    proc = subprocess.run(
        [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "FABRIC_API_SECURITY_OK" in proc.stdout

