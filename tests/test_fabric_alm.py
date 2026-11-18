"""Hermetic execution checks for selective Fabric promotion and reviewed scope."""

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _guid(number: int) -> str:
    return f"00000000-0000-0000-0000-{number:012x}"


def _source_items(count: int = 3) -> list[dict[str, object]]:
    names = ["Notebook_1", "Orders", "Configuration"]
    types = ["Notebook", "Dataflow", "VariableLibrary"]
    return [
        {
            "itemId": _guid(100 + index),
            "itemDisplayName": names[index] if index < 3 else f"Item_{index}",
            "itemType": types[index] if index < 3 else "Notebook",
            "targetItemId": _guid(500 + index),
        }
        for index in range(count)
    ]


def _run_alm(
    tmp_path: Path,
    *,
    scope: str = "Selected",
    selection: object = None,
    raw_selection: str | None = None,
    reviewed: bool = True,
    sources: list[dict[str, object]] | None = None,
    plan_only: bool = False,
    stale: bool = False,
    mutate_unselected: bool = False,
    break_pairing: bool = False,
    workflow_steps: bool = False,
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell 7 is required to exercise the promotion script")
    source_items = _source_items() if sources is None else sources
    targets = [
        {
            "itemId": _guid(500 + index),
            "itemDisplayName": (
                "Renamed configuration" if item["itemType"] == "VariableLibrary"
                else item["itemDisplayName"]
            ),
            "itemType": item["itemType"],
            "sourceItemId": item["itemId"],
            "lastDeploymentTime": "2026-01-01T00:00:00Z",
        }
        for index, item in enumerate(source_items)
    ]
    targets.extend(
        [
            {
                "itemId": _guid(9000),
                "itemDisplayName": "Unselected warehouse",
                "itemType": "Warehouse",
                "lastDeploymentTime": "2026-01-01T00:00:00Z",
            },
            {
                "itemId": _guid(9001),
                "itemDisplayName": "Configuration",
                "itemType": "VariableLibrary",
                "lastDeploymentTime": "2026-01-01T00:00:00Z",
            },
        ]
    )
    selected = [{"name": "Notebook_1", "type": "Notebook"}] if selection is None else selection
    scenario = {
        "scope": scope,
        "selection": json.dumps(selected) if raw_selection is None else raw_selection,
        "reviewed": reviewed,
        "sources": source_items,
        "targets": targets,
        "plan_only": plan_only,
        "stale": stale,
        "mutate_unselected": mutate_unselected,
        "break_pairing": break_pairing,
        "workflow_steps": workflow_steps,
    }
    if workflow_steps:
        workflow = (ROOT / ".github" / "workflows" / "promote-fabric-alm.yml").read_text(
            encoding="utf-8"
        )
        planning, separator, promotion = workflow.partition("\n  promote:\n")
        assert separator
        scenario["planning_script"] = textwrap.dedent(planning.partition("        run: |\n")[2])
        scenario["promotion_script"] = textwrap.dedent(promotion.partition("        run: |\n")[2])
    script = r"""
$ErrorActionPreference = 'Stop'
$global:Scenario = $env:ALM_SCENARIO | ConvertFrom-Json
$global:Sources = @($global:Scenario.sources)
$global:Targets = @($global:Scenario.targets)
$global:Calls = @()
$global:ActiveValueSet = ''
function global:Import-Module {
    param($Name, [switch]$Force)
    if ([IO.Path]::GetFileName($Name) -ne 'FabricApi.psm1') { throw 'Unexpected module import' }
}
function global:Get-FabricAccessToken { return 'synthetic-access-token' }
function global:Start-Sleep { param($Seconds) }
function global:Get-MockPage {
    param($Items, $Uri)
    $Values = @($Items)
    if ($Uri -match '\?page=2$') { return @{ value = @($Values | Select-Object -Skip 1) } }
    if ($Values.Count -gt 1) {
        return @{ value = @($Values[0]); continuationUri = "${Uri}?page=2" }
    }
    return @{ value = $Values }
}
function global:Invoke-FabricRequest {
    param($Method, $Uri, $Token, $SkillName, $Body, [switch]$FetchResult)
    if ($SkillName -notin @('deployment-pipelines-authoring-cli', 'variable-library-cli')) {
        throw 'Missing expected Fabric skill attribution'
    }
    $Payload = if ($Body) { $Body | ConvertFrom-Json } else { $null }
    $global:Calls += [pscustomobject]@{ Method = $Method; Uri = $Uri; Body = $Payload }
    if ($Method -eq 'Post') {
        foreach ($Requested in @($Payload.items)) {
            $Source = @($global:Sources | Where-Object itemId -eq $Requested.sourceItemId)[0]
            if (-not $Source.targetItemId) {
                $Source.targetItemId = '00000000-0000-0000-0000-000000009999'
            }
            $Target = @($global:Targets | Where-Object itemId -eq $Source.targetItemId)
            if (-not $Target.Count) {
                $Target = @([pscustomobject]@{
                    itemId = $Source.targetItemId
                    itemDisplayName = $Source.itemDisplayName
                    itemType = $Source.itemType
                    sourceItemId = $Source.itemId
                    lastDeploymentTime = ''
                })
                $global:Targets += $Target
            }
            $Target[0].lastDeploymentTime = '2026-02-01T00:00:00Z'
            if ($global:Scenario.break_pairing) { $Source.targetItemId = '' }
        }
        if ($global:Scenario.mutate_unselected) {
            $Unselected = @($global:Targets | Where-Object {
                $_.itemDisplayName -eq 'Unselected warehouse'
            })[0]
            $Unselected.itemDisplayName = 'Unexpected change'
        }
        return
    }
    if ($Method -eq 'Patch') {
        $global:ActiveValueSet = $Payload.properties.activeValueSetName
        return
    }
    if ($Uri -match '/variableLibraries/') {
        return @{ properties = @{ activeValueSetName = $global:ActiveValueSet } }
    }
    if ($Uri -match '/stages(\?page=2)?$') {
        $Stages = @(
            [pscustomobject]@{
                id = '00000000-0000-0000-0000-000000000001'
                displayName = 'Development'; order = 0
                workspaceId = '00000000-0000-0000-0000-000000000011'
            },
            [pscustomobject]@{
                id = '00000000-0000-0000-0000-000000000002'
                displayName = 'Test'; order = 1
                workspaceId = '00000000-0000-0000-0000-000000000012'
            },
            [pscustomobject]@{
                id = '00000000-0000-0000-0000-000000000003'
                displayName = 'Production'; order = 2
                workspaceId = '00000000-0000-0000-0000-000000000013'
            }
        )
        return Get-MockPage -Items $Stages -Uri $Uri
    }
    if ($Uri -match '/stages/00000000-0000-0000-0000-000000000002/items') {
        return Get-MockPage -Items $global:Sources -Uri $Uri
    }
    if ($Uri -match '/stages/00000000-0000-0000-0000-000000000003/items') {
        return Get-MockPage -Items $global:Targets -Uri $Uri
    }
    throw "Unexpected mock Fabric request: $Method $Uri"
}
$Parameters = @{
    DeploymentPipelineId = '00000000-0000-0000-0000-000000000099'
    SourceStageName = 'Test'
    TargetStageName = 'Production'
    PromotionScope = $global:Scenario.scope
    SelectedItemsJson = $global:Scenario.selection
    DependenciesReviewed = [bool]$global:Scenario.reviewed
    DeploymentNote = 'Synthetic selective release'
    VariableLibraryName = 'Configuration'
    ActiveValueSetName = 'prod'
}
if ($global:Scenario.workflow_steps) {
    & ([scriptblock]::Create($global:Scenario.planning_script))
    $PlanLine = Get-Content -LiteralPath $env:GITHUB_OUTPUT |
        Where-Object { $_.StartsWith('promotion_plan=') } | Select-Object -Last 1
    $PlanJson = $PlanLine.Substring('promotion_plan='.Length)
}
else {
    $PlanJson = (& .\scripts\Invoke-FabricAlm.ps1 -Operation PlanPromotion @Parameters | Out-String)
}
if ($LASTEXITCODE) {
    @{ Phase = 'plan'; Calls = @($global:Calls) } | ConvertTo-Json -Depth 30 -Compress
    exit 1
}
$Plan = $PlanJson | ConvertFrom-Json
$PlanCallCount = $global:Calls.Count
if ($global:Scenario.plan_only) {
    @{ Plan = $Plan; Calls = @($global:Calls) } | ConvertTo-Json -Depth 30 -Compress
    exit 0
}
if ($global:Scenario.stale) {
    $global:Sources[0].itemId = '00000000-0000-0000-0000-000000008888'
}
if ($global:Scenario.workflow_steps) {
    $env:INPUT_REVIEWED_PLAN = $PlanJson
    $ResultJson = (& ([scriptblock]::Create($global:Scenario.promotion_script)) | Out-String)
}
else {
    $ResultJson = (& .\scripts\Invoke-FabricAlm.ps1 -Operation Promote @Parameters `
        -ReviewedPlanJson $PlanJson | Out-String)
}
$ExitCode = [int]$LASTEXITCODE
$Result = if (-not $ExitCode) { $ResultJson | ConvertFrom-Json } else { $null }
@{ Plan = $Plan; Result = $Result; Calls = @($global:Calls); PlanCallCount = $PlanCallCount } |
    ConvertTo-Json -Depth 30 -Compress
exit $ExitCode
"""
    environment = os.environ | {
        "ALM_SCENARIO": json.dumps(scenario),
        "AZURE_CLIENT_ID": "",
        "AZURE_TENANT_ID": "",
        "AZURE_CLIENT_SECRET": "",
        "GITHUB_STEP_SUMMARY": str(tmp_path / "promotion-summary.md"),
        "GITHUB_OUTPUT": str(tmp_path / "promotion-output.txt"),
        "FABRIC_ACTIVE_VALUE_SET_NAME": "",
        "FABRIC_VARIABLE_LIBRARY_NAME": "Configuration" if workflow_steps else "",
        "FABRIC_DEPLOYMENT_PIPELINE_ID": _guid(99),
        "FABRIC_SOURCE_STAGE_NAME": "Test",
        "FABRIC_TARGET_STAGE_NAME": "Production",
        "FABRIC_DEPLOYMENT_PLAN_ID": "",
        "FABRIC_DEPLOYMENT_NOTE": "Synthetic selective release",
        "INPUT_ACTIVE_VALUE_SET_NAME": "prod",
        "INPUT_PROMOTION_SCOPE": scope,
        "INPUT_SELECTED_ITEMS": str(scenario["selection"]),
        "INPUT_DEPENDENCIES_REVIEWED": str(reviewed).lower(),
        "INPUT_PREVIEW_DEPLOYMENT_PLAN": "false",
        "INPUT_REVIEWED_PLAN": "",
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


@pytest.mark.parametrize("paired", [True, False], ids=["update", "create"])
def test_selected_promotion_uses_source_ids_and_leaves_other_items_alone(
    tmp_path: Path, paired: bool
) -> None:
    sources = _source_items()
    if not paired:
        sources[0]["targetItemId"] = ""
    result = _run_alm(tmp_path, sources=sources)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["Result"]["Status"] == "Succeeded"
    assert output["Result"]["VerifiedItemCount"] == 1
    assert output["Plan"]["VariableLibrary"] is None
    assert output["Plan"]["Items"][0]["Action"] == ("Update" if paired else "Create")
    calls = output["Calls"]
    assert all(call["Method"] == "Get" for call in calls[: output["PlanCallCount"]])
    mutations = [call for call in calls if call["Method"] != "Get"]
    assert len(mutations) == 1
    assert mutations[0]["Body"]["sourceStageId"] == _guid(2)
    assert mutations[0]["Body"]["targetStageId"] == _guid(3)
    assert mutations[0]["Body"]["items"] == [
        {"sourceItemId": _guid(100), "itemType": "Notebook"}
    ]


def test_workflow_plan_output_drives_only_the_approved_selection(tmp_path: Path) -> None:
    result = _run_alm(tmp_path, workflow_steps=True)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["Result"]["Status"] == "Succeeded"
    assert output["Result"]["VerifiedItemCount"] == 1
    posts = [call for call in output["Calls"] if call["Method"] == "Post"]
    assert len(posts) == 1
    assert posts[0]["Body"]["items"] == [{"sourceItemId": _guid(100), "itemType": "Notebook"}]
    assert all(call["Method"] == "Get" for call in output["Calls"][: output["PlanCallCount"]])
    summary = (tmp_path / "promotion-summary.md").read_text(encoding="utf-8-sig")
    for field, label in [
        ("SourceWorkspaceId", "Source workspace"),
        ("TargetWorkspaceId", "Target workspace"),
    ]:
        assert f"{label}: <code>{output['Plan'][field]}</code>" in summary
    assert "Synthetic selective release" in summary


def test_read_only_plan_identifies_unpaired_creations(tmp_path: Path) -> None:
    sources = _source_items()
    sources[0]["targetItemId"] = ""
    result = _run_alm(tmp_path, sources=sources, plan_only=True)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert len(output["Plan"]["Items"]) == 1
    assert output["Plan"]["Items"][0]["Action"] == "Create"
    assert output["Plan"]["Items"][0]["TargetItemId"] == ""
    assert all(call["Method"] == "Get" for call in output["Calls"])


@pytest.mark.parametrize(
    ("selection", "raw", "reviewed", "expected_error"),
    [
        ([], None, True, "between 1 and 300"),
        ({"name": "Notebook_1", "type": "Notebook"}, None, True, "JSON array"),
        (None, "[", True, "JSON"),
        ([{"name": "Missing", "type": "Notebook"}], None, True, "found 0"),
        ([{"name": "Notebook_1", "type": "Dataflow"}], None, True, "found 0"),
        ([{"name": "Notebook_1", "type": "Notebook"}] * 2, None, True, "Duplicate"),
        ([{"name": "Notebook_1", "type": "Notebook", "extra": True}], None, True, "only"),
        (None, None, False, "DependenciesReviewed"),
    ],
)
def test_invalid_selections_never_deploy(
    tmp_path: Path, selection: object, raw: str | None, reviewed: bool, expected_error: str
) -> None:
    result = _run_alm(tmp_path, selection=selection, raw_selection=raw, reviewed=reviewed)
    assert result.returncode != 0
    assert expected_error in result.stderr
    assert all(call["Method"] == "Get" for call in json.loads(result.stdout)["Calls"])


def test_ambiguous_names_fail_without_deployment(tmp_path: Path) -> None:
    sources = _source_items()
    sources.append(sources[0] | {"itemId": _guid(8000)})
    result = _run_alm(tmp_path, sources=sources)
    assert result.returncode != 0
    assert "found 2" in result.stderr
    assert all(call["Method"] == "Get" for call in json.loads(result.stdout)["Calls"])


def test_all_scope_rejects_a_conflicting_selection(tmp_path: Path) -> None:
    result = _run_alm(tmp_path, scope="All")
    assert result.returncode != 0
    assert "All scope cannot be combined" in result.stderr
    assert all(call["Method"] == "Get" for call in json.loads(result.stdout)["Calls"])


@pytest.mark.parametrize("count", [300, 301])
def test_all_scope_is_explicit_and_enforces_fabric_limit(tmp_path: Path, count: int) -> None:
    result = _run_alm(tmp_path, scope="All", selection=[], sources=_source_items(count))
    output = json.loads(result.stdout)
    mutations = [call for call in output["Calls"] if call["Method"] == "Post"]
    if count == 301:
        assert result.returncode != 0
        assert "between 1 and 300" in result.stderr
        assert not mutations
    else:
        assert result.returncode == 0, result.stderr
        assert len(mutations) == 1
        assert len(mutations[0]["Body"]["items"]) == 300
        assert output["Result"]["VerifiedItemCount"] == 300


def test_selected_variable_library_activates_only_its_paired_target(tmp_path: Path) -> None:
    result = _run_alm(
        tmp_path, selection=[{"name": "Configuration", "type": "VariableLibrary"}]
    )
    assert result.returncode == 0, result.stderr
    patches = [call for call in json.loads(result.stdout)["Calls"] if call["Method"] == "Patch"]
    assert len(patches) == 1
    assert patches[0]["Uri"].endswith("/variableLibraries/" + _guid(502))
    assert patches[0]["Body"] == {"properties": {"activeValueSetName": "prod"}}


def test_reviewed_plan_rejects_changed_source_identity(tmp_path: Path) -> None:
    result = _run_alm(tmp_path, stale=True)
    assert result.returncode != 0
    assert "Promotion plan changed" in result.stderr
    assert all(call["Method"] == "Get" for call in json.loads(result.stdout)["Calls"])


@pytest.mark.parametrize(
    ("change", "expected_error"),
    [
        ({"mutate_unselected": True}, "Unselected target item metadata changed"),
        ({"break_pairing": True}, "selected item pairing could not be verified"),
    ],
)
def test_promotion_reports_readback_failures(
    tmp_path: Path, change: dict[str, bool], expected_error: str
) -> None:
    result = _run_alm(
        tmp_path,
        mutate_unselected=change.get("mutate_unselected", False),
        break_pairing=change.get("break_pairing", False),
    )
    assert result.returncode != 0
    assert expected_error in result.stderr
