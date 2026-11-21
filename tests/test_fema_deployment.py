"""Hermetic tests for FEMA Fabric workspace deployment and schema bootstrap."""

import ast
import base64
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
GUID_WS = "11111111-1111-4111-8111-111111111111"
GUID_FOLDER = "77777777-7777-4777-8777-777777777777"
GUID_LH = "22222222-2222-4222-8222-222222222222"
GUID_ENV = "33333333-3333-4333-8333-333333333333"
GUID_SM = "44444444-4444-4444-8444-444444444444"


def _load_notebook(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def test_assessment_notebook_supports_schema_bootstrap_and_matches_tmdl() -> None:
    nb_path = ROOT / "notebooks" / "fabric-portfolio-assessment.ipynb"
    nb = _load_notebook(nb_path)
    cells = nb["cells"]
    assert isinstance(cells, list)

    code_by_id: dict[str, str] = {}
    for cell in cells:
        assert isinstance(cell, dict)
        if cell.get("cell_type") == "code":
            source = "".join(cell["source"])
            ast.parse(source)
            cell_id = str(cell.get("id", ""))
            code_by_id[cell_id] = source

    assert "INITIALIZE_SCHEMA_ONLY = False" in code_by_id["parameters"]
    assert "REFRESH_SEMANTIC_MODEL = True" in code_by_id["parameters"]
    for guarded_id in ("preview", "assess"):
        assert "INITIALIZE_SCHEMA_ONLY" in code_by_id[guarded_id]
    for source in code_by_id.values():
        assert "displayHTML" not in source

    persist_src = code_by_id["persist-delta"]
    assert "mode('ignore').saveAsTable(table_name)" in persist_src
    assert "_refresh_direct_lake_model" in persist_src

    # Verify every TMDL table column matches the Spark StructType schema in persist-delta.
    tmdl_dir = (
        ROOT
        / "powerbi"
        / "ETL Migration Assessment Model.SemanticModel"
        / "definition"
        / "tables"
    )
    table_map: dict[str, list[str]] = {}
    for tmdl_file in sorted(tmdl_dir.glob("*.tmdl")):
        text = tmdl_file.read_text(encoding="utf-8")
        entity_match = re.search(r"entityName:\s*(\S+)", text)
        assert entity_match is not None
        entity_name = entity_match.group(1)
        columns = re.findall(r"^\tcolumn\s+([A-Za-z0-9_]+)", text, flags=re.MULTILINE)
        table_map[entity_name] = columns

    assert len(table_map) == 8
    for entity_name, columns in table_map.items():
        assert f"'{entity_name}'" in persist_src
        for col in columns:
            assert f"StructField('{col}'" in persist_src


def test_deploy_fema_notebook_is_valid_nbformat() -> None:
    nb_path = ROOT / "notebooks" / "Deploy_FEMA.ipynb"
    nb = _load_notebook(nb_path)
    assert nb["nbformat"] == 4
    cells = nb["cells"]
    assert isinstance(cells, list)
    code_cells = [c for c in cells if isinstance(c, dict) and c.get("cell_type") == "code"]
    assert len(code_cells) >= 3
    combined = []
    for cell in code_cells:
        src = "".join(cell["source"])
        ast.parse(src)
        combined.append(src)
    full_code = "\n".join(combined)
    assert "INITIALIZE_SCHEMA_ONLY" in full_code
    assert "semanticmodelid=" in full_code


def test_build_powerbi_report_and_notebook_payload_builders(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        pytest.skip("Node.js is required to test payload builders")

    report_out = tmp_path / "report-payload.json"
    rpt_proc = subprocess.run(
        [
            "node",
            str(ROOT / "scripts" / "build-powerbi-report-payload.mjs"),
            "--semantic-model-id",
            GUID_SM,
            "--out",
            str(report_out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rpt_proc.returncode == 0, rpt_proc.stderr
    rpt_payload = json.loads(report_out.read_text(encoding="utf-8"))
    assert rpt_payload["definition"]["format"] == "PBIR"
    parts = {part["path"]: part["payload"] for part in rpt_payload["definition"]["parts"]}
    assert not any(path == ".pbi" or path.startswith(".pbi/") for path in parts)
    pbir = json.loads(base64.b64decode(parts["definition.pbir"]).decode("utf-8"))
    assert pbir["datasetReference"] == {
        "byConnection": {"connectionString": f"semanticmodelid={GUID_SM}"}
    }

    nb_out = tmp_path / "notebook-payload.json"
    nb_proc = subprocess.run(
        [
            "node",
            str(ROOT / "scripts" / "build-notebook-payload.mjs"),
            "--workspace-id",
            GUID_WS,
            "--lakehouse-id",
            GUID_LH,
            "--lakehouse-name",
            "ETL_Migration_Assessment_Lakehouse",
            "--environment-id",
            GUID_ENV,
            "--out",
            str(nb_out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert nb_proc.returncode == 0, nb_proc.stderr
    nb_payload = json.loads(nb_out.read_text(encoding="utf-8"))
    assert nb_payload["definition"]["format"] == "ipynb"
    nb_parts = {part["path"]: part["payload"] for part in nb_payload["definition"]["parts"]}
    nb_doc = json.loads(base64.b64decode(nb_parts["notebook-content.ipynb"]).decode("utf-8"))
    assert nb_doc["metadata"]["dependencies"] == {
        "lakehouse": {
            "default_lakehouse": GUID_LH,
            "default_lakehouse_name": "ETL_Migration_Assessment_Lakehouse",
            "default_lakehouse_workspace_id": GUID_WS,
            "known_lakehouses": [{"id": GUID_LH}],
        },
        "environment": {
            "environmentId": GUID_ENV,
            "workspaceId": GUID_WS,
        },
    }


def test_build_fema_bundle_creates_clean_manifest(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        pytest.skip("Node.js is required to test bundle builder")

    bundle_dir = ROOT / "build" / f"test-fema-bundle-{os.getpid()}"
    try:
        proc = subprocess.run(
            [
                "node",
                str(ROOT / "scripts" / "build-fema-bundle.mjs"),
                "--out",
                str(bundle_dir),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        manifest = json.loads((bundle_dir / "bundle-manifest.json").read_text(encoding="utf-8"))
        files = set(manifest["filesIncluded"])
        assert "scripts/deployment_order.json" in files
        assert "scripts/Deploy-AcceleratorWorkspace.ps1" in files
        assert "notebooks/Deploy_FEMA.ipynb" in files
        assert "notebooks/fabric-portfolio-assessment.ipynb" in files
        assert not any(".pbi/" in item or item.endswith(".env") for item in files)
    finally:
        shutil.rmtree(bundle_dir, ignore_errors=True)


def _run_workspace_installer(
    tmp_path: Path,
    *,
    existing_items: bool,
) -> subprocess.CompletedProcess[str]:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is required to exercise Deploy-AcceleratorWorkspace.ps1")

    wheel_file = tmp_path / "fabric_etl_migration_accelerator-1.0.0-py3-none-any.whl"
    wheel_file.write_bytes(b"PK\x03\x04synthetic-wheel")
    summary_path = tmp_path / "summary.json"
    calls_path = tmp_path / "calls.json"

    harness = f"""
$ErrorActionPreference = 'Stop'
$env:FABRIC_WORKSPACE_ID = '99999999-9999-4999-8999-999999999999'
$global:ExistingItems = {'$true' if existing_items else '$false'}
$global:Calls = [System.Collections.Generic.List[object]]::new()
$NbId = '55555555-5555-4555-8555-555555555555'
$RptId = '66666666-6666-4666-8666-666666666666'

function global:Import-Module {{
    param($Name, [switch]$Force)
    if ([IO.Path]::GetFileName($Name) -ne 'FabricApi.psm1') {{ throw "Unexpected module: $Name" }}
}}
function global:Get-FabricAccessToken {{
    param(
        [switch]$AllowAzCliFallback,
        [switch]$UseAzCli,
        [string]$Resource = 'https://api.fabric.microsoft.com'
    )
    return 'synthetic-token'
}}
function global:Invoke-FabricFileUpload {{
    param($Uri, $FilePath, $Token, $SkillName, $Mode, $FormFieldName)
    $global:Calls.Add([pscustomobject]@{{ Method = 'UPLOAD'; Uri = $Uri; Mode = $Mode }})
    return $null
}}
function global:Invoke-FabricRequest {{
    param($Method, $Uri, $Token, $SkillName, $Body, [switch]$FetchResult, [switch]$NoLroPoll)
    $Payload = if ($Body) {{ $Body | ConvertFrom-Json }} else {{ $null }}
    $global:Calls.Add([pscustomobject]@{{ Method = $Method; Uri = $Uri; Body = $Payload }})

    if ($Method -eq 'Get' -and $Uri -match '/workspaces$') {{
        return @{{
            value = @(@{{ id = '{GUID_WS}'; displayName = 'Synthetic Workspace' }})
            continuationUri = ''
        }}
    }}
    if ($Method -eq 'Get' -and $Uri -match '/folders$') {{
        if (-not $global:ExistingItems) {{
            return @{{ value = @(); continuationUri = '' }}
        }}
        return @{{
            value = @(@{{ id = '{GUID_FOLDER}'; displayName = 'FEMA' }})
            continuationUri = ''
        }}
    }}
    if ($Method -eq 'Get' -and $Uri -match '/lakehouses/{GUID_LH}$') {{
        return @{{
            id = '{GUID_LH}'
            properties = @{{}}
        }}
    }}
    if ($Method -eq 'Get' -and $Uri -match '/refreshes') {{
        return @{{
            value = @(@{{ status = 'Completed' }})
        }}
    }}
    if ($Method -eq 'Get' -and $Uri -match '/environments/{GUID_ENV}$') {{
        return @{{
            id = '{GUID_ENV}'
            properties = @{{ publishDetails = @{{ state = 'Success' }} }}
        }}
    }}
    if (
        $Method -eq 'Get' -and
        $Uri -match '/(lakehouses|environments|notebooks|semanticModels|reports)$'
    ) {{
        $Col = $Matches[1]
        if (-not $global:ExistingItems) {{
            return @{{ value = @(); continuationUri = '' }}
        }}
        $Map = @{{
            lakehouses = @{{
                id = '{GUID_LH}'; displayName = 'ETL_Migration_Assessment_Lakehouse'
            }}
            environments = @{{
                id = '{GUID_ENV}'; displayName = 'ETL_Migration_Assessment_Env'
            }}
            notebooks = @{{
                id = $NbId; displayName = 'ETL Migration Assessment'
            }}
            semanticModels = @{{
                id = '{GUID_SM}'; displayName = 'ETL Migration Assessment Model'
            }}
            reports = @{{
                id = $RptId; displayName = 'ETL Migration Assessment'
            }}
        }}
        return @{{ value = @($Map[$Col]); continuationUri = '' }}
    }}
    if ($Method -eq 'Patch') {{
        return @{{}}
    }}
    if ($Method -eq 'Post') {{
        if ($Uri -match '/refreshes$') {{ return @{{}} }}
        if ($Uri -match '/folders$') {{
            return @{{ id = '{GUID_FOLDER}'; displayName = $Payload.displayName }}
        }}
        if ($Uri -match '/items/[^/]+/move$') {{ return @{{ value = @() }} }}
        if ($Uri -match '/staging/publish') {{ return @{{}} }}
        if ($Uri -match '/jobs/execute/instances') {{ return @{{ status = 'Completed' }} }}
        if ($Uri -match '/updateDefinition') {{ return @{{}} }}
        if ($Uri -match '/lakehouses$') {{
            return @{{ id = '{GUID_LH}'; displayName = $Payload.displayName }}
        }}
        if ($Uri -match '/environments$') {{
            return @{{ id = '{GUID_ENV}'; displayName = $Payload.displayName }}
        }}
        if ($Uri -match '/notebooks$') {{
            return @{{ id = $NbId; displayName = $Payload.displayName }}
        }}
        if ($Uri -match '/semanticModels$') {{
            return @{{ id = '{GUID_SM}'; displayName = $Payload.displayName }}
        }}
        if ($Uri -match '/reports$') {{
            return @{{ id = $RptId; displayName = $Payload.displayName }}
        }}
    }}
    throw "Unhandled mocked Fabric call: $Method $Uri"
}}

& '{(ROOT / "scripts" / "Deploy-AcceleratorWorkspace.ps1").as_posix()}' `
    -WorkspaceName 'Synthetic Workspace' `
    -WheelPath '{wheel_file.as_posix()}' `
    -SkipWheelBuild `
    -SkipFabricApp `
    -OutputSummaryPath '{summary_path.as_posix()}'

$global:Calls | ConvertTo-Json -Depth 10 |
    Set-Content -LiteralPath '{calls_path.as_posix()}' -Encoding utf8
"""
    return subprocess.run(
        [pwsh, "-NoProfile", "-Command", harness],
        capture_output=True,
        text=True,
        check=False,
    )


def test_workspace_installer_fresh_and_idempotent_upgrade(tmp_path: Path) -> None:
    fresh_dir = tmp_path / "fresh"
    fresh_dir.mkdir()
    fresh = _run_workspace_installer(fresh_dir, existing_items=False)
    assert fresh.returncode == 0, fresh.stderr
    fresh_summary = json.loads((fresh_dir / "summary.json").read_text(encoding="utf-8"))
    assert fresh_summary["mode"] == "deployed"
    assert fresh_summary["workspaceId"] == GUID_WS
    assert fresh_summary["folderId"] == GUID_FOLDER
    assert fresh_summary["folderName"] == "FEMA"
    assert fresh_summary["lakehouseId"] == GUID_LH
    assert fresh_summary["semanticModelId"] == GUID_SM

    fresh_calls = json.loads((fresh_dir / "calls.json").read_text(encoding="utf-8"))
    uris = [call["Uri"] for call in fresh_calls]
    assert any(
        u.endswith("/folders") and c["Method"] == "Post" and c["Body"]["displayName"] == "FEMA"
        for c, u in zip(fresh_calls, uris, strict=True)
    )
    for item_suffix in (
        "/lakehouses",
        "/environments",
        "/notebooks",
        "/semanticModels",
        "/reports",
    ):
        created_call = next(
            c for c in fresh_calls if c["Method"] == "Post" and c["Uri"].endswith(item_suffix)
        )
        assert created_call["Body"]["folderId"] == GUID_FOLDER
    assert any(
        "/staging/libraries/" in u and c["Method"] == "UPLOAD"
        for c, u in zip(fresh_calls, uris, strict=True)
    )
    assert any("/jobs/execute/instances" in u for u in uris)
    bootstrap_call = next(c for c in fresh_calls if "/jobs/execute/instances" in c["Uri"])
    params = {p["name"]: p["value"] for p in bootstrap_call["Body"]["parameters"]}
    assert params["INITIALIZE_SCHEMA_ONLY"] is True
    assert params["PERSIST_DELTA_TABLES"] is False

    upgrade_dir = tmp_path / "upgrade"
    upgrade_dir.mkdir()
    upgrade = _run_workspace_installer(upgrade_dir, existing_items=True)
    assert upgrade.returncode == 0, upgrade.stderr
    upgrade_calls = json.loads((upgrade_dir / "calls.json").read_text(encoding="utf-8"))
    move_calls = [
        c for c in upgrade_calls if c["Method"] == "Post" and c["Uri"].endswith("/move")
    ]
    assert len(move_calls) == 5
    assert all(c["Body"]["targetFolderId"] == GUID_FOLDER for c in move_calls)
    update_uris = [
        c["Uri"] for c in upgrade_calls if "/updateDefinition" in c["Uri"]
    ]
    assert len(update_uris) == 3  # Notebook, SemanticModel, Report updated in place
    assert any(
        "/notebooks/" in u and u.endswith("?updateMetadata=true") for u in update_uris
    )
    assert any(
        "/reports/" in u and u.endswith("?updateMetadata=true") for u in update_uris
    )
    assert any(
        "/semanticModels/" in u and u.endswith("/updateDefinition") for u in update_uris
    )


def test_fabric_environment_excludes_web_server_dependencies() -> None:
    env_text = (ROOT / "scripts" / "fabric-environment.yml").read_text(encoding="utf-8")
    for forbidden in ("fastapi", "uvicorn", "typer", "pyjwt", "python-multipart"):
        assert forbidden not in env_text.casefold()
    assert "defusedxml" in env_text
    assert "pydantic" in env_text
