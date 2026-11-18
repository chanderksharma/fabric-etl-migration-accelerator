"""Hermetic workflow checks for safe Fabric deployment pipeline provisioning."""

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PIPELINE_ID = "00000000-0000-0000-0000-000000000101"


def _run_provisioning(
    tmp_path: Path,
    *,
    existing: bool = False,
    dry_run: bool = False,
    failure: str = "",
    stages: list[str] | None = None,
    workflow_steps: bool = False,
    workspaces: tuple[str, str, str] = (
        "Synthetic Dev",
        "Synthetic Test",
        "Synthetic Prod",
    ),
    admin_group_id: str = "",
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell 7 is required to exercise pipeline provisioning")
    stage_names = ["Development", "Test", "Production"] if stages is None else stages
    scenario = {
        "existing": existing,
        "dry_run": dry_run,
        "failure": failure,
        "stage_names": stage_names,
        "workflow_steps": workflow_steps,
        "admin_group_id": admin_group_id,
    }
    if workflow_steps:
        workflow = (
            ROOT / ".github" / "workflows" / "create-fabric-deployment-pipeline.yml"
        ).read_text(encoding="utf-8")
        scenario["script"] = textwrap.dedent(workflow.partition("        run: |\n")[2])
    script = r"""
$ErrorActionPreference = 'Stop'
$global:Scenario = $env:PROVISIONING_SCENARIO | ConvertFrom-Json
$global:Calls = @()
$global:Created = $false
$global:Assignments = @{}
$global:GroupAdmins = @{}
$DevId = '00000000-0000-0000-0000-000000000201'
$TestId = '00000000-0000-0000-0000-000000000202'
$ProdId = '00000000-0000-0000-0000-000000000203'
$DevStageId = '00000000-0000-0000-0000-000000000301'
$TestStageId = '00000000-0000-0000-0000-000000000302'
$ProdStageId = '00000000-0000-0000-0000-000000000303'
$GroupId = '00000000-0000-0000-0000-000000000501'
if ($global:Scenario.failure -eq 'already') { $global:Assignments[$DevStageId] = $DevId }
if ($global:Scenario.failure -eq 'occupied') { $global:Assignments[$TestStageId] = $DevId }
if ($global:Scenario.existing -and $global:Scenario.failure -in @('', 'group-existing')) {
    $global:Assignments[$DevStageId] = $DevId
    $global:Assignments[$TestStageId] = $TestId
    $global:Assignments[$ProdStageId] = $ProdId
}
if ($global:Scenario.failure -eq 'group-existing') {
    $global:GroupAdmins['00000000-0000-0000-0000-000000000101'] = $GroupId
}
function global:Import-Module {
    param($Name, [switch]$Force)
    if ([IO.Path]::GetFileName($Name) -ne 'FabricApi.psm1') { throw 'Unexpected module import' }
}
function global:Get-FabricAccessToken { return 'synthetic-access-token' }
function global:Invoke-FabricRequest {
    param($Method, $Uri, $Token, $SkillName, $Body)
    if ($SkillName -ne 'deployment-pipelines-authoring-cli') {
        throw 'Missing provisioning skill attribution'
    }
    $Payload = if ($Body) { $Body | ConvertFrom-Json } else { $null }
    $global:Calls += [pscustomobject]@{ Method = $Method; Uri = $Uri; Body = $Payload }
    if ($Method -eq 'Post') {
        if ($Uri -match '/deploymentPipelines/([^/]+)/roleAssignments$') {
            $global:GroupAdmins[$Matches[1]] = $Payload.principal.id
            return
        }
        if ($Uri -match '/stages/([^/]+)/assignWorkspace$') {
            $global:Assignments[$Matches[1]] = $Payload.workspaceId
            return
        }
        if (-not $Uri.EndsWith('/deploymentPipelines')) { throw 'Unexpected write' }
        if ($global:Scenario.failure -eq 'forbidden') {
            throw 'Fabric request failed (403): InsufficientPrivileges'
        }
        $global:Created = $true
        return @{ id = '00000000-0000-0000-0000-000000000101' }
    }
    if ($Method -ne 'Get') { throw 'Provisioning attempted an unexpected mutation' }
    if ($Uri -match '/deploymentPipelines/([^/]+)/roleAssignments$') {
        $PipelineId = $Matches[1]
        $Roles = @()
        if (
            $global:Scenario.failure -eq 'group-existing' -or
            $global:GroupAdmins.ContainsKey($PipelineId)
        ) {
            $AdminId = if ($global:GroupAdmins.ContainsKey($PipelineId)) {
                $global:GroupAdmins[$PipelineId]
            }
            else { $GroupId }
            $Roles += @{
                principal = @{ id = $AdminId; type = 'Group' }
                role = 'Admin'
            }
        }
        return @{ value = $Roles }
    }
    if ($Uri.EndsWith('/workspaces?roles=Admin')) {
        return @{ value = @(
            @{ id = $DevId; displayName = 'Synthetic Dev'; type = 'Workspace' }
            @{ id = $TestId; displayName = 'Synthetic Test'; type = 'Workspace' }
            @{ id = $ProdId; displayName = 'Synthetic Prod'; type = 'Workspace' }
        ) }
    }
    if ($Uri.EndsWith('/deploymentPipelines')) {
        if ($global:Scenario.failure -eq 'invalid-collection') {
            return @{ value = 'invalid collection' }
        }
        return @{
            value = @(
                @{ id = '00000000-0000-0000-0000-000000000100'; displayName = 'Unrelated' }
            )
            continuationUri = $Uri + '?page=2'
        }
    }
    if ($Uri.EndsWith('/deploymentPipelines?page=2')) {
        $Items = @()
        if ($global:Scenario.existing) {
            $Items += @{
                id = '00000000-0000-0000-0000-000000000101'
                displayName = 'Synthetic ALM'
            }
        }
        if ($global:Scenario.failure -eq 'split-pipelines') {
            $Items += @{
                id = '00000000-0000-0000-0000-000000000103'
                displayName = 'Other Pipeline'
            }
        }
        if ($global:Scenario.failure -eq 'duplicate') {
            $Items += @{
                id = '00000000-0000-0000-0000-000000000102'
                displayName = 'Synthetic ALM'
            }
        }
        return @{ value = $Items }
    }
    if ($Uri.EndsWith('00000000-0000-0000-0000-000000000100/stages')) {
        if ($global:Scenario.failure -eq 'other-pipeline') {
            return @{ value = @(@{ displayName = 'QA'; workspaceId = $TestId }) }
        }
        if ($global:Scenario.failure -eq 'reuse-by-workspace') {
            return @{ value = @(
                @{
                    id = '00000000-0000-0000-0000-000000000401'
                    order = 0; displayName = 'Development'; workspaceId = $DevId
                },
                @{
                    id = '00000000-0000-0000-0000-000000000402'
                    order = 1; displayName = 'Test'
                },
                @{
                    id = '00000000-0000-0000-0000-000000000403'
                    order = 2; displayName = 'Production'
                }
            ) }
        }
        if ($global:Scenario.failure -eq 'split-pipelines') {
            return @{ value = @(@{ displayName = 'Development'; workspaceId = $DevId }) }
        }
        return @{ value = @() }
    }
    if ($Uri -match '/stages/([^/]+)$') {
        if ($Matches[1] -eq '00000000-0000-0000-0000-000000000402') {
            return @{ id = $Matches[1]; workspaceId = $global:Assignments[$Matches[1]] }
        }
        return @{ id = $Matches[1]; workspaceId = $global:Assignments[$Matches[1]] }
    }
    if ($Uri.EndsWith('/stages')) {
        if ($global:Scenario.failure -eq 'split-pipelines') {
            return @{ value = @(@{
                id = $TestStageId; order = 1; displayName = 'Test'; workspaceId = $TestId
            }) }
        }
        return @{
            value = @(@{
                id = $DevStageId; order = 0; displayName = 'Development'
                workspaceId = $global:Assignments[$DevStageId]
            })
            continuationUri = $Uri + '?page=2'
        }
    }
    if ($Uri.EndsWith('/stages?page=2')) {
        $Middle = if ($global:Scenario.failure -eq 'stage-mismatch') { 'QA' } else { 'Test' }
        return @{
            value = @(
                @{
                    id = $TestStageId; order = 1; displayName = $Middle
                    workspaceId = $global:Assignments[$TestStageId]
                },
                @{
                    id = $ProdStageId; order = 2; displayName = 'Production'
                    workspaceId = $global:Assignments[$ProdStageId]
                }
            )
        }
    }
    if ($Uri.EndsWith('/deploymentPipelines/00000000-0000-0000-0000-000000000100')) {
        return @{ id = '00000000-0000-0000-0000-000000000100'; displayName = 'Unrelated' }
    }
    if ($Uri.EndsWith('/deploymentPipelines/00000000-0000-0000-0000-000000000101')) {
        if (-not ($global:Created -or $global:Scenario.existing)) {
            throw 'Readback requested before creation'
        }
        return @{ id = '00000000-0000-0000-0000-000000000101'; displayName = 'Synthetic ALM' }
    }
    throw "Unexpected provisioning request: $Method $Uri"
}
if ($global:Scenario.workflow_steps) {
    $ResultJson = (& ([scriptblock]::Create($global:Scenario.script)) | Out-String)
}
else {
    $Parameters = @{
        DisplayName = 'Synthetic ALM'
        Description = 'Synthetic provisioning fixture'
        StageNames = @($global:Scenario.stage_names)
        PipelineAdminGroupId = $global:Scenario.admin_group_id
        DryRun = [bool]$global:Scenario.dry_run
    }
    $Parameters.WorkspaceNames = @(
        [string]$env:INPUT_DEV_WORKSPACE_NAME
        [string]$env:INPUT_TEST_WORKSPACE_NAME
        [string]$env:INPUT_PROD_WORKSPACE_NAME
    )
    $ResultJson = (& .\scripts\New-FabricDeploymentPipeline.ps1 @Parameters | Out-String)
}
$ExitCode = [int]$LASTEXITCODE
$Result = if (-not $ExitCode) { $ResultJson | ConvertFrom-Json } else { $null }
@{ Result = $Result; Calls = @($global:Calls) } | ConvertTo-Json -Depth 15 -Compress
exit $ExitCode
"""
    environment = os.environ | {
        "PROVISIONING_SCENARIO": json.dumps(scenario),
        "AZURE_CLIENT_ID": "",
        "AZURE_TENANT_ID": "",
        "AZURE_CLIENT_SECRET": "",
        "GITHUB_STEP_SUMMARY": str(tmp_path / "provisioning-summary.md"),
        "GITHUB_OUTPUT": str(tmp_path / "provisioning-output.txt"),
        "INPUT_PIPELINE_NAME": "Synthetic ALM",
        "INPUT_PIPELINE_DESCRIPTION": "Synthetic provisioning fixture",
        "INPUT_DRY_RUN": str(dry_run).lower(),
        "INPUT_DEV_STAGE_NAME": "Development",
        "INPUT_TEST_STAGE_NAME": "Test",
        "INPUT_PROD_STAGE_NAME": "Production",
        "INPUT_DEV_WORKSPACE_NAME": workspaces[0],
        "INPUT_TEST_WORKSPACE_NAME": workspaces[1],
        "INPUT_PROD_WORKSPACE_NAME": workspaces[2],
        "INPUT_PIPELINE_ADMIN_GROUP_ID": admin_group_id,
    }
    return subprocess.run(
        [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_workflow_adds_and_verifies_optional_admin_group(tmp_path: Path) -> None:
    group_id = "00000000-0000-0000-0000-000000000501"
    result = _run_provisioning(tmp_path, workflow_steps=True, admin_group_id=group_id)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["Result"]["PipelineAdminGroup"] == {
        "GroupId": group_id,
        "Status": "AddedAdmin",
    }
    role_posts = [
        call
        for call in output["Calls"]
        if call["Method"] == "Post" and call["Uri"].endswith("/roleAssignments")
    ]
    assert len(role_posts) == 1
    assert role_posts[0]["Body"] == {
        "principal": {"id": group_id, "type": "Group"},
        "role": "Admin",
    }
    assert sum(
        call["Method"] == "Get" and call["Uri"].endswith("/roleAssignments")
        for call in output["Calls"]
    ) == 2


def test_new_pipeline_dry_run_previews_group_access_without_writes(tmp_path: Path) -> None:
    group_id = "00000000-0000-0000-0000-000000000501"
    result = _run_provisioning(
        tmp_path, dry_run=True, workflow_steps=True, admin_group_id=group_id
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["Result"]["PipelineAdminGroup"] == {
        "GroupId": group_id,
        "Status": "WouldAddAfterCreate",
    }
    assert all(call["Method"] == "Get" for call in output["Calls"])


def test_matching_group_admin_is_reused_without_writes(tmp_path: Path) -> None:
    group_id = "00000000-0000-0000-0000-000000000501"
    result = _run_provisioning(
        tmp_path,
        existing=True,
        failure="group-existing",
        admin_group_id=group_id,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["Result"]["PipelineAdminGroup"]["Status"] == "AlreadyAdmin"
    assert all(call["Method"] == "Get" for call in output["Calls"])


def test_invalid_admin_group_id_fails_before_api_calls(tmp_path: Path) -> None:
    result = _run_provisioning(tmp_path, admin_group_id="not-a-guid")
    assert result.returncode != 0
    assert "valid pipeline Admin group ID" in result.stderr
    assert json.loads(result.stdout)["Calls"] == []


@pytest.mark.parametrize(
    ("existing", "dry_run", "scenario", "expected_statuses", "expected_writes"),
    [
        (False, True, "", ["WouldAssign", "WouldAssign", "WouldAssign"], 0),
        (False, False, "", ["Assigned", "Assigned", "Assigned"], 4),
        (True, False, "already", ["AlreadyAssigned", "Assigned", "Assigned"], 2),
    ],
)
def test_workflow_attaches_only_requested_empty_stages(
    tmp_path: Path,
    existing: bool,
    dry_run: bool,
    scenario: str,
    expected_statuses: list[str],
    expected_writes: int,
) -> None:
    result = _run_provisioning(
        tmp_path, existing=existing, dry_run=dry_run, failure=scenario,
        workflow_steps=True,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assignments = output["Result"]["WorkspaceAssignments"]
    assert [entry["StageName"] for entry in assignments] == [
        "Development",
        "Test",
        "Production",
    ]
    assert [entry["Status"] for entry in assignments] == expected_statuses
    writes = [call for call in output["Calls"] if call["Method"] != "Get"]
    assert len(writes) == expected_writes
    stage_ids = {
        "Development": "00000000-0000-0000-0000-000000000301",
        "Test": "00000000-0000-0000-0000-000000000302",
        "Production": "00000000-0000-0000-0000-000000000303",
    }
    for entry, call in zip(
        (entry for entry in assignments if entry["Status"] == "Assigned"),
        (call for call in writes if call["Uri"].endswith("/assignWorkspace")),
        strict=True,
    ):
        assert call["Body"] == {"workspaceId": entry["WorkspaceId"]}
        stage_uri = f"/stages/{stage_ids[entry['StageName']]}"
        assert call["Uri"].endswith(f"{stage_uri}/assignWorkspace")
        assert any(
            read["Method"] == "Get" and read["Uri"].endswith(stage_uri)
            for read in output["Calls"]
        )


@pytest.mark.parametrize(
    ("existing", "scenario", "test_workspace", "error"),
    [
        (False, "other-pipeline", "Synthetic Test", "will not be moved"),
        (True, "occupied", "Synthetic Test", "will not be replaced"),
        (False, "", "Synthetic Dev", "Workspace names must be distinct"),
        (False, "", "Missing", "with Admin access"),
    ],
)
def test_assignment_conflicts_fail_before_creating_or_attaching(
    tmp_path: Path, existing: bool, scenario: str, test_workspace: str, error: str
) -> None:
    result = _run_provisioning(
        tmp_path, existing=existing, failure=scenario,
        workspaces=("Synthetic Dev", test_workspace, "Synthetic Prod"),
    )
    assert result.returncode != 0
    assert error in result.stderr
    assert all(call["Method"] == "Get" for call in json.loads(result.stdout)["Calls"])


def test_reuse_by_workspace_returns_existing_pipeline_and_assigns_empty_stage(
    tmp_path: Path,
) -> None:
    result = _run_provisioning(
        tmp_path,
        existing=False,
        dry_run=False,
        failure="reuse-by-workspace",
        workflow_steps=True,
        workspaces=("Synthetic Dev", "Synthetic Test", "Synthetic Prod"),
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["Result"]["Status"] == "Reused"
    assert output["Result"]["DisplayName"] == "Unrelated"
    assert output["Result"]["PipelineId"] == "00000000-0000-0000-0000-000000000100"
    assignments = output["Result"]["WorkspaceAssignments"]
    assert [entry["Status"] for entry in assignments] == [
        "AlreadyAssigned",
        "Assigned",
        "Assigned",
    ]
    exported = (tmp_path / "provisioning-output.txt").read_text(encoding="utf-8-sig")
    assert "pipeline_id=00000000-0000-0000-0000-000000000100" in exported
    assert "pipeline_name=Unrelated" in exported


@pytest.mark.parametrize(
    ("scenario", "error"),
    [
        ("other-pipeline", "does not match requested stage"),
        ("split-pipelines", "assigned to different pipelines"),
    ],
)
def test_reuse_by_workspace_rejects_mismatched_or_split_assignments(
    tmp_path: Path, scenario: str, error: str
) -> None:
    result = _run_provisioning(
        tmp_path,
        existing=False,
        failure=scenario,
        workspaces=("Synthetic Dev", "Synthetic Test", "Synthetic Prod"),
    )
    assert result.returncode != 0
    assert error in result.stderr
    assert all(call["Method"] == "Get" for call in json.loads(result.stdout)["Calls"])


def test_workflow_creates_pipeline_and_exports_readback_id(tmp_path: Path) -> None:
    result = _run_provisioning(tmp_path, workflow_steps=True)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["Result"]["Status"] == "Created"
    assert output["Result"]["PipelineId"] == PIPELINE_ID
    mutations = [call for call in output["Calls"] if call["Method"] != "Get"]
    assert len(mutations) == 4
    creates = [call for call in mutations if call["Uri"].endswith("/deploymentPipelines")]
    assert len(creates) == 1
    assert creates[0]["Body"] == {
        "displayName": "Synthetic ALM",
        "description": "Synthetic provisioning fixture",
        "stages": [
            {"displayName": "Development", "isPublic": False},
            {"displayName": "Test", "isPublic": False},
            {"displayName": "Production", "isPublic": True},
        ],
    }
    assert len(
        [call for call in mutations if call["Uri"].endswith("/assignWorkspace")]
    ) == 3
    exported = (tmp_path / "provisioning-output.txt").read_text(encoding="utf-8-sig")
    assert f"pipeline_id={PIPELINE_ID}" in exported
    assert any(call["Uri"].endswith("/stages?page=2") for call in output["Calls"])


def test_workflow_preview_never_creates_or_exports_an_uncreated_id(tmp_path: Path) -> None:
    result = _run_provisioning(tmp_path, dry_run=True, workflow_steps=True)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["Result"]["Status"] == "WouldCreate"
    assert output["Result"]["PipelineId"] == ""
    assert all(call["Method"] == "Get" for call in output["Calls"])
    output_file = tmp_path / "provisioning-output.txt"
    if output_file.exists():
        assert "pipeline_id=" not in output_file.read_text(encoding="utf-8-sig")


def test_missing_required_workspace_fails_before_api_calls(tmp_path: Path) -> None:
    result = _run_provisioning(
        tmp_path, workspaces=("Synthetic Dev", "Synthetic Test", "")
    )
    assert result.returncode != 0
    assert "Workspace names must be distinct, non-empty" in result.stderr
    assert json.loads(result.stdout)["Calls"] == []


@pytest.mark.parametrize("dry_run", [True, False])
def test_matching_existing_pipeline_is_verified_and_reused_unchanged(
    tmp_path: Path, dry_run: bool
) -> None:
    result = _run_provisioning(tmp_path, existing=True, dry_run=dry_run)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["Result"]["Status"] == "Reused"
    assert output["Result"]["PipelineId"] == PIPELINE_ID
    assert all(call["Method"] == "Get" for call in output["Calls"])
    assert any(call["Uri"].endswith("/stages?page=2") for call in output["Calls"])


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("duplicate", "More than one"),
        ("stage-mismatch", "Stage names or order differ"),
        ("invalid-collection", "invalid provisioning collection"),
    ],
)
def test_conflicting_existing_pipelines_are_not_replaced(
    tmp_path: Path, failure: str, message: str
) -> None:
    result = _run_provisioning(tmp_path, existing=True, failure=failure)
    assert result.returncode != 0
    assert message in result.stderr
    assert all(call["Method"] == "Get" for call in json.loads(result.stdout)["Calls"])


@pytest.mark.parametrize(
    "stages", [["Development", "test", "Test"], ["Development", "", "Production"]]
)
def test_invalid_stage_names_fail_before_api_calls(tmp_path: Path, stages: list[str]) -> None:
    result = _run_provisioning(tmp_path, stages=stages)
    assert result.returncode != 0
    assert "Stage names must be distinct" in result.stderr
    assert json.loads(result.stdout)["Calls"] == []


def test_creation_permission_failure_is_explicit(tmp_path: Path) -> None:
    result = _run_provisioning(tmp_path, failure="forbidden")
    assert result.returncode != 0
    assert "Fabric administrator" in result.stderr
    assert json.loads(result.stdout)["Result"] is None
