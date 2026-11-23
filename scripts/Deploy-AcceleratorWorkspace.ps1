#!/usr/bin/env pwsh
# Copyright (c) Microsoft Corporation.
# Microsoft Confidential - Internal InnerSource Use Only.
#Requires -Version 7.0

<#
.SYNOPSIS
    Deploys the full Microsoft Fabric ETL Migration Accelerator stack into a Fabric workspace.
.DESCRIPTION
    Implements a FEMA-style, idempotent workspace installation in dependency order:
      1. Resolve (or optionally create) the target Fabric workspace
      2. Create or reuse the target workspace Folder (default: FEMA)
      3. Create or reuse the assessment Lakehouse inside the folder
      4. Build/locate the Python wheel and publish a Fabric Runtime 2.0 Environment inside the folder
      5. Create or update the Assessment Notebook inside the folder bound to the Lakehouse and Environment
      6. Bootstrap the eight empty etl_* Delta tables (idempotent schema-on-first-deploy)
      7. Create or update the Direct Lake Semantic Model inside the folder bound to Workspace + Lakehouse
      8. Create or update the Power BI Report inside the folder bound to the Semantic Model
      9. Optionally build, deploy, and configure the Fabric Analyst App (rayfin) inside the folder
.PARAMETER WorkspaceName
    Target Fabric workspace display name.
.PARAMETER WorkspaceId
    Target Fabric workspace GUID. Defaults to FABRIC_WORKSPACE_ID when WorkspaceName is omitted.
.PARAMETER CreateWorkspace
    Creates WorkspaceName on CapacityId if it does not already exist.
.PARAMETER CapacityId
    Fabric capacity GUID used when CreateWorkspace is set.
.PARAMETER FolderName
    Workspace folder display name (or '/'-separated folder path) that holds all deployed items.
    Pass an empty string to deploy directly at the workspace root.
.PARAMETER LakehouseName
    Display name for the assessment Lakehouse.
.PARAMETER EnvironmentName
    Display name for the Fabric Runtime 2.0 Environment.
.PARAMETER NotebookName
    Display name for the assessment Notebook.
.PARAMETER SemanticModelName
    Display name for the Direct Lake Semantic Model.
.PARAMETER ReportName
    Display name for the Power BI Report.
.PARAMETER WheelPath
    Optional pre-built accelerator wheel (.whl). When omitted, builds via `uv build --wheel`.
.PARAMETER EnvironmentYmlPath
    Path to the pip external-libraries YAML file for the Fabric Environment.
.PARAMETER SkipWheelBuild
    Skips `uv build --wheel` and uses WheelPath or the newest wheel under dist/.
.PARAMETER SkipEnvironmentPublish
    Skips uploading libraries to and publishing the Fabric Environment.
.PARAMETER SkipSchemaBootstrap
    Skips running the notebook with INITIALIZE_SCHEMA_ONLY=true after deployment.
.PARAMETER SkipFabricApp
    Skips building and deploying apps/etl-migration-assessment-app via rayfin.
.PARAMETER UseAzCli
    Acquires the Fabric token directly via `az account get-access-token`.
.PARAMETER OutputSummaryPath
    Optional path to write a nonsecret JSON summary of deployed Fabric item IDs.
.PARAMETER DryRun
    Validates local assets, builds all definition payloads in a temporary directory,
    checks for unresolved tokens, and prints the deployment plan without calling Fabric.
.EXAMPLE
    ./scripts/Deploy-AcceleratorWorkspace.ps1 -WorkspaceName 'ETL Migration Dev' -DryRun
.EXAMPLE
    ./scripts/Deploy-AcceleratorWorkspace.ps1 -WorkspaceName 'ETL Migration Dev' -UseAzCli
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceName,

    [Parameter(Mandatory = $false)]
    [string]$WorkspaceId,

    [Parameter(Mandatory = $false)]
    [switch]$CreateWorkspace,

    [Parameter(Mandatory = $false)]
    [string]$CapacityId,

    [Parameter(Mandatory = $false)]
    [string]$FolderName = 'FEMA',

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$LakehouseName = 'ETL_Migration_Assessment_Lakehouse',

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$EnvironmentName = 'ETL_Migration_Assessment_Env',

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$NotebookName = 'ETL Migration Assessment',

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$SemanticModelName = 'ETL Migration Assessment Model',

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$ReportName = 'ETL Migration Assessment',

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$FabricAppName = 'fema-etl-migration-app',

    [Parameter(Mandatory = $false)]
    [string]$WheelPath,

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$EnvironmentYmlPath = (Join-Path $PSScriptRoot 'fabric-environment.yml'),

    [Parameter(Mandatory = $false)]
    [switch]$SkipWheelBuild,

    [Parameter(Mandatory = $false)]
    [switch]$SkipEnvironmentPublish,

    [Parameter(Mandatory = $false)]
    [switch]$SkipSchemaBootstrap,

    [Parameter(Mandatory = $false)]
    [switch]$SkipFabricApp,

    [Parameter(Mandatory = $false)]
    [switch]$UseAzCli,

    [Parameter(Mandatory = $false)]
    [string]$OutputSummaryPath,

    [Parameter(Mandatory = $false)]
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$FabricApi = 'https://api.fabric.microsoft.com/v1'
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$GuidPattern = '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$'

Import-Module (Join-Path $PSScriptRoot 'FabricApi.psm1') -Force

function Get-FabricCollection {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri,

        [Parameter(Mandatory = $true)]
        [string]$Token,

        [Parameter(Mandatory = $true)]
        [string]$SkillName
    )

    $NextUri = $Uri
    $Visited = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    while (-not [string]::IsNullOrWhiteSpace($NextUri)) {
        if (-not $Visited.Add($NextUri)) {
            throw "Repeated Fabric pagination URI: $NextUri"
        }
        $Page = Invoke-FabricRequest -Method Get -Uri $NextUri -Token $Token -SkillName $SkillName
        foreach ($Entry in @($Page.value)) {
            $Entry
        }
        $NextUri = [string]$Page.continuationUri
    }
}

function Resolve-TargetWorkspace {
    [CmdletBinding()]
    param(
        [string]$Name,
        [string]$Id,
        [switch]$Create,
        [string]$Capacity,
        [string]$Token
    )

    if (-not [string]::IsNullOrWhiteSpace($Name) -and -not [string]::IsNullOrWhiteSpace($Id)) {
        throw 'Provide either -WorkspaceName or -WorkspaceId, not both.'
    }
    if ([string]::IsNullOrWhiteSpace($Name) -and [string]::IsNullOrWhiteSpace($Id)) {
        $Id = $env:FABRIC_WORKSPACE_ID
    }
    if (-not [string]::IsNullOrWhiteSpace($Id)) {
        if ($Id -notmatch $GuidPattern) {
            throw "WorkspaceId must be a valid GUID: $Id"
        }
        $Ws = Invoke-FabricRequest -Method Get -Uri "$FabricApi/workspaces/$Id" `
            -Token $Token -SkillName 'onelake-catalog-cli'
        return [pscustomobject]@{
            id          = [string]$Ws.id
            displayName = [string]$Ws.displayName
        }
    }

    if ([string]::IsNullOrWhiteSpace($Name)) {
        throw 'Provide -WorkspaceName or -WorkspaceId (or set FABRIC_WORKSPACE_ID).'
    }

    $Workspaces = @(Get-FabricCollection -Uri "$FabricApi/workspaces" -Token $Token -SkillName 'onelake-catalog-cli')
    $Match = @($Workspaces | Where-Object { $_.displayName -ceq $Name })
    if ($Match.Count -gt 1) {
        throw "Multiple workspaces matched exact displayName '$Name'."
    }
    if ($Match.Count -eq 1) {
        return [pscustomobject]@{
            id          = [string]$Match[0].id
            displayName = [string]$Match[0].displayName
        }
    }

    if (-not $Create) {
        throw "Workspace '$Name' was not found. Pass -CreateWorkspace with -CapacityId to create it."
    }
    if ([string]::IsNullOrWhiteSpace($Capacity) -or $Capacity -notmatch $GuidPattern) {
        throw 'Provide a valid -CapacityId GUID when creating a new workspace.'
    }

    $CreateBody = @{
        displayName = $Name
        capacityId  = $Capacity
        description = 'Microsoft Fabric ETL Migration Accelerator workspace'
    } | ConvertTo-Json -Compress
    $Created = Invoke-FabricRequest -Method Post -Uri "$FabricApi/workspaces" `
        -Token $Token -SkillName 'onelake-catalog-cli' -Body $CreateBody
    return [pscustomobject]@{
        id          = [string]$Created.id
        displayName = [string]$Created.displayName
    }
}

function Resolve-OrCreateFolderPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$WorkspaceGuid,

        [Parameter(Mandatory = $true)]
        [string]$FolderPath,

        [Parameter(Mandatory = $true)]
        [string]$Token
    )

    $Segments = @(
        $FolderPath.Replace('\', '/').Split('/') |
            ForEach-Object { $_.Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($Segments.Count -eq 0) {
        return $null
    }

    $Folders = @(Get-FabricCollection -Uri "$FabricApi/workspaces/$WorkspaceGuid/folders" -Token $Token -SkillName 'onelake-catalog-cli')
    $ParentId = $null
    $Action = 'reused'
    $Current = $null
    foreach ($Segment in $Segments) {
        $Match = @(
            $Folders | Where-Object {
                $_.displayName -ceq $Segment -and (
                    ([string]::IsNullOrWhiteSpace($ParentId) -and [string]::IsNullOrWhiteSpace([string]$_.parentFolderId)) -or
                    ([string]$_.parentFolderId -eq $ParentId)
                )
            }
        )
        if ($Match.Count -gt 1) {
            throw "Multiple folders matched '$Segment' in workspace $WorkspaceGuid."
        }
        if ($Match.Count -eq 1) {
            $Current = $Match[0]
            $ParentId = [string]$Current.id
            continue
        }

        $BodyHash = @{ displayName = $Segment }
        if (-not [string]::IsNullOrWhiteSpace($ParentId)) {
            $BodyHash['parentFolderId'] = $ParentId
        }
        $Created = Invoke-FabricRequest -Method Post `
            -Uri "$FabricApi/workspaces/$WorkspaceGuid/folders" `
            -Token $Token -SkillName 'onelake-catalog-cli' `
            -Body ($BodyHash | ConvertTo-Json -Compress)
        $Current = $Created
        $ParentId = [string]$Created.id
        $Folders += $Created
        $Action = 'created'
    }

    return [pscustomobject]@{
        id          = [string]$Current.id
        displayName = $FolderPath.Trim()
        action      = $Action
    }
}

function Move-ItemToFolderIfNeeded {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$WorkspaceGuid,

        [Parameter(Mandatory = $true)]
        [string]$ItemId,

        [string]$CurrentFolderId,

        [string]$TargetFolderId,

        [Parameter(Mandatory = $true)]
        [string]$Token
    )

    if ([string]::IsNullOrWhiteSpace($TargetFolderId)) {
        return
    }
    if ($CurrentFolderId -eq $TargetFolderId) {
        return
    }

    $MoveBody = @{ targetFolderId = $TargetFolderId } | ConvertTo-Json -Compress
    $null = Invoke-FabricRequest -Method Post `
        -Uri "$FabricApi/workspaces/$WorkspaceGuid/items/$ItemId/move" `
        -Token $Token -SkillName 'onelake-catalog-cli' -Body $MoveBody
}

function Resolve-OrCreateSimpleItem {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$WorkspaceGuid,

        [Parameter(Mandatory = $true)]
        [string]$Collection,

        [Parameter(Mandatory = $true)]
        [string]$DisplayName,

        [Parameter(Mandatory = $true)]
        [string]$Description,

        [string]$FolderId,

        [Parameter(Mandatory = $true)]
        [string]$SkillName,

        [Parameter(Mandatory = $true)]
        [string]$Token
    )

    $Items = @(Get-FabricCollection -Uri "$FabricApi/workspaces/$WorkspaceGuid/$Collection" -Token $Token -SkillName $SkillName)
    $Existing = @($Items | Where-Object { $_.displayName -ceq $DisplayName })
    if ($Existing.Count -gt 1) {
        throw "Multiple $Collection items matched exact displayName '$DisplayName'."
    }
    if ($Existing.Count -eq 1) {
        $ItemId = [string]$Existing[0].id
        Move-ItemToFolderIfNeeded -WorkspaceGuid $WorkspaceGuid -ItemId $ItemId `
            -CurrentFolderId ([string]$Existing[0].folderId) -TargetFolderId $FolderId -Token $Token
        return [pscustomobject]@{
            id          = $ItemId
            displayName = [string]$Existing[0].displayName
            action      = 'reused'
        }
    }

    $BodyHash = @{
        displayName = $DisplayName
        description = $Description
    }
    if (-not [string]::IsNullOrWhiteSpace($FolderId)) {
        $BodyHash['folderId'] = $FolderId
    }
    $Body = $BodyHash | ConvertTo-Json -Compress
    $Created = Invoke-FabricRequest -Method Post `
        -Uri "$FabricApi/workspaces/$WorkspaceGuid/$Collection" `
        -Token $Token -SkillName $SkillName -Body $Body
    if (-not [string]::IsNullOrWhiteSpace([string]$Created.id)) {
        return [pscustomobject]@{
            id          = [string]$Created.id
            displayName = [string]$Created.displayName
            action      = 'created'
        }
    }
    $Refetched = @(
        Get-FabricCollection -Uri "$FabricApi/workspaces/$WorkspaceGuid/$Collection" `
            -Token $Token -SkillName $SkillName |
            Where-Object { $_.displayName -ceq $DisplayName }
    )
    if ($Refetched.Count -ne 1) {
        throw "Created $Collection item '$DisplayName' could not be resolved by displayName."
    }
    return [pscustomobject]@{
        id          = [string]$Refetched[0].id
        displayName = [string]$Refetched[0].displayName
        action      = 'created'
    }
}

function Upsert-DefinedItem {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$WorkspaceGuid,

        [Parameter(Mandatory = $true)]
        [string]$Collection,

        [Parameter(Mandatory = $true)]
        [string]$DisplayName,

        [Parameter(Mandatory = $true)]
        [string]$PayloadPath,

        [string]$FolderId,

        [Parameter(Mandatory = $true)]
        [string]$SkillName,

        [Parameter(Mandatory = $true)]
        [string]$Token
    )

    $PayloadText = Get-Content -LiteralPath $PayloadPath -Raw
    $PayloadObj = $PayloadText | ConvertFrom-Json
    $Items = @(Get-FabricCollection -Uri "$FabricApi/workspaces/$WorkspaceGuid/$Collection" -Token $Token -SkillName $SkillName)
    $Existing = @($Items | Where-Object { $_.displayName -ceq $DisplayName })
    if ($Existing.Count -gt 1) {
        throw "Multiple $Collection items matched exact displayName '$DisplayName'."
    }
    if ($Existing.Count -eq 1) {
        $ItemId = [string]$Existing[0].id
        Move-ItemToFolderIfNeeded -WorkspaceGuid $WorkspaceGuid -ItemId $ItemId `
            -CurrentFolderId ([string]$Existing[0].folderId) -TargetFolderId $FolderId -Token $Token
        $HasPlatform = @($PayloadObj.definition.parts.path) -contains '.platform'
        $UpdateUri = if ($HasPlatform) {
            "$FabricApi/workspaces/$WorkspaceGuid/$Collection/$ItemId/updateDefinition?updateMetadata=true"
        }
        else {
            "$FabricApi/workspaces/$WorkspaceGuid/$Collection/$ItemId/updateDefinition"
        }
        $UpdateBody = @{ definition = $PayloadObj.definition } | ConvertTo-Json -Depth 20 -Compress
        $null = Invoke-FabricRequest -Method Post `
            -Uri $UpdateUri `
            -Token $Token -SkillName $SkillName -Body $UpdateBody
        return [pscustomobject]@{
            id          = $ItemId
            displayName = $DisplayName
            action      = 'updated'
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($FolderId)) {
        $PayloadObj | Add-Member -NotePropertyName folderId -NotePropertyValue $FolderId -Force
        $PayloadText = $PayloadObj | ConvertTo-Json -Depth 20 -Compress
    }
    $Created = Invoke-FabricRequest -Method Post `
        -Uri "$FabricApi/workspaces/$WorkspaceGuid/$Collection" `
        -Token $Token -SkillName $SkillName -Body $PayloadText
    if (-not [string]::IsNullOrWhiteSpace([string]$Created.id)) {
        return [pscustomobject]@{
            id          = [string]$Created.id
            displayName = [string]$Created.displayName
            action      = 'created'
        }
    }
    $Refetched = @(
        Get-FabricCollection -Uri "$FabricApi/workspaces/$WorkspaceGuid/$Collection" `
            -Token $Token -SkillName $SkillName |
            Where-Object { $_.displayName -ceq $DisplayName }
    )
    if ($Refetched.Count -ne 1) {
        throw "Created $Collection item '$DisplayName' could not be resolved by displayName."
    }
    return [pscustomobject]@{
        id          = [string]$Refetched[0].id
        displayName = [string]$Refetched[0].displayName
        action      = 'created'
    }
}

function Wait-EnvironmentIdle {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$WorkspaceGuid,

        [Parameter(Mandatory = $true)]
        [string]$EnvironmentId,

        [Parameter(Mandatory = $true)]
        [string]$Token
    )

    for ($Attempt = 0; $Attempt -lt 120; $Attempt++) {
        $EnvItem = Invoke-FabricRequest -Method Get `
            -Uri "$FabricApi/workspaces/$WorkspaceGuid/environments/$EnvironmentId" `
            -Token $Token -SkillName 'spark-cli'
        $State = [string]$EnvItem.properties.publishDetails.state
        if ($State -notin @('Running', 'Waiting')) {
            return $State
        }
        Start-Sleep -Seconds 5
    }
    throw "Timed out waiting for environment $EnvironmentId publish state."
}

function Resolve-WheelArtifacts {
    [CmdletBinding()]
    param(
        [string]$ExplicitPath,
        [switch]$SkipBuild,
        [switch]$IsDryRun
    )

    $WheelPatterns = @(
        'etl_migration_core-*.whl',
        'etl_portfolio_assessment-*.whl',
        'etl_target_fabric-*.whl'
    )

    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        if (Test-Path -LiteralPath $ExplicitPath -PathType Leaf) {
            return @((Resolve-Path -LiteralPath $ExplicitPath).Path)
        }
        if (Test-Path -LiteralPath $ExplicitPath -PathType Container) {
            $SearchDir = (Resolve-Path -LiteralPath $ExplicitPath).Path
        }
        else {
            throw "WheelPath not found: $ExplicitPath"
        }
    }
    else {
        $SearchDir = Join-Path $RepoRoot 'dist'
        if (-not $SkipBuild -and -not $IsDryRun) {
            if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
                throw 'uv is required to build the Python wheels (or pass -WheelPath / -SkipWheelBuild).'
            }
            if (Test-Path -LiteralPath $SearchDir -PathType Container) {
                Get-ChildItem -LiteralPath $SearchDir -Filter '*.whl' -File | Remove-Item -Force
            }
            Push-Location $RepoRoot
            try {
                & uv build --all-packages --wheel
                if ($LASTEXITCODE -ne 0) {
                    throw 'uv build --all-packages --wheel failed.'
                }
            }
            finally {
                Pop-Location
            }
        }
    }

    if (Test-Path -LiteralPath $SearchDir -PathType Container) {
        $Selected = [System.Collections.Generic.List[string]]::new()
        $Missing = [System.Collections.Generic.List[string]]::new()
        foreach ($Pattern in $WheelPatterns) {
            $Latest = Get-ChildItem -LiteralPath $SearchDir -Filter $Pattern -File |
                Sort-Object LastWriteTimeUtc -Descending |
                Select-Object -First 1
            if ($Latest) {
                $Selected.Add($Latest.FullName)
            }
            else {
                $Missing.Add($Pattern)
            }
        }
        if ($Selected.Count -eq $WheelPatterns.Count) {
            return $Selected.ToArray()
        }
        if (-not $IsDryRun -and $Selected.Count -gt 0) {
            throw "Incomplete workspace wheels in $SearchDir; missing: $($Missing -join ', ')"
        }
    }

    if ($IsDryRun) {
        return @('<built via uv build --all-packages --wheel>')
    }
    throw "No workspace wheels found in $SearchDir. Run 'uv build --all-packages --wheel' or pass -WheelPath."
}

function New-RandomSecretHex {
    $Bytes = [byte[]]::new(32)
    [Security.Cryptography.RandomNumberGenerator]::Fill($Bytes)
    return ([Convert]::ToHexString($Bytes)).ToLowerInvariant()
}

function Restore-RecordedFabricAppIfRecoverable {
    [CmdletBinding()]
    [OutputType([bool])]
    param(
        [Parameter(Mandatory = $true)]
        [string]$WorkspaceGuid,

        [Parameter(Mandatory = $true)]
        [string]$WorkspaceName,

        [Parameter(Mandatory = $true)]
        [string]$AppDirectory,

        [Parameter(Mandatory = $true)]
        [string]$AppName,

        [Parameter(Mandatory = $true)]
        [string]$Token
    )

    $DeploymentsPath = Join-Path $AppDirectory 'rayfin/.deployments.json'
    if (-not (Test-Path -LiteralPath $DeploymentsPath -PathType Leaf)) {
        return $false
    }

    try {
        $Registry = Get-Content -LiteralPath $DeploymentsPath -Raw | ConvertFrom-Json
    }
    catch {
        Write-Warning "Could not read Rayfin deployment registry '$DeploymentsPath': $($_.Exception.Message)"
        return $false
    }

    $Deployment = $Registry.deployments.$WorkspaceName
    if ($null -eq $Deployment -and -not [string]::IsNullOrWhiteSpace([string]$Registry.active)) {
        $Deployment = $Registry.deployments.([string]$Registry.active)
    }
    if (
        $null -eq $Deployment -or
        [string]$Deployment.fabricWorkspaceId -ne $WorkspaceGuid -or
        [string]$Deployment.itemName -cne $AppName -or
        [string]$Deployment.fabricItemId -notmatch $GuidPattern
    ) {
        return $false
    }

    $RecordedId = [string]$Deployment.fabricItemId
    $Recoverable = Invoke-FabricRequest -Method Get `
        -Uri "$FabricApi/workspaces/$WorkspaceGuid/recoverableItems?type=AppBackend&recoverableByMe=true" `
        -Token $Token -SkillName 'fabric-app-dev'
    $Match = @(
        $Recoverable.value |
            Where-Object {
                [string]$_.id -eq $RecordedId -and
                [string]$_.type -eq 'AppBackend' -and
                [string]$_.displayName -ceq $AppName
            }
    )
    if ($Match.Count -eq 0) {
        return $false
    }

    Write-Host "Restoring deleted Fabric App backend '$AppName' ($RecordedId)."
    $null = Invoke-FabricRequest -Method Post `
        -Uri "$FabricApi/workspaces/$WorkspaceGuid/recoverableItems/$RecordedId/recover" `
        -Token $Token -SkillName 'fabric-app-dev'
    Write-Host 'Fabric App backend restored successfully.'
    return $true
}

$OrderFile = Join-Path $PSScriptRoot 'deployment_order.json'
if (-not (Test-Path -LiteralPath $OrderFile -PathType Leaf)) {
    throw "Missing deployment manifest: $OrderFile"
}
$null = Get-Content -LiteralPath $OrderFile -Raw | ConvertFrom-Json

$NotebookSource = Join-Path $RepoRoot 'notebooks/fabric-portfolio-assessment.ipynb'
$SemanticModelBuilder = Join-Path $PSScriptRoot 'build-powerbi-semantic-model-payload.mjs'
$ReportBuilder = Join-Path $PSScriptRoot 'build-powerbi-report-payload.mjs'
$NotebookBuilder = Join-Path $PSScriptRoot 'build-notebook-payload.mjs'
$FabricAppDir = Join-Path $RepoRoot 'apps/etl-migration-assessment-app'

foreach ($RequiredPath in @($NotebookSource, $SemanticModelBuilder, $ReportBuilder, $NotebookBuilder)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "Required deployment asset missing: $RequiredPath"
    }
}
if (-not $SkipEnvironmentPublish -and -not (Test-Path -LiteralPath $EnvironmentYmlPath -PathType Leaf)) {
    throw "Environment YAML file missing: $EnvironmentYmlPath"
}

$ResolvedWheels = @(Resolve-WheelArtifacts -ExplicitPath $WheelPath -SkipBuild:$SkipWheelBuild -IsDryRun:$DryRun)
$ResolvedWheel = $ResolvedWheels[-1]

$TempDir = Join-Path ([IO.Path]::GetTempPath()) ("fabric-etl-deploy-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $TempDir -Force | Out-Null

try {
    if ($DryRun) {
        $SyntheticWsId = if ($WorkspaceId -match $GuidPattern) { $WorkspaceId } else { '11111111-1111-4111-8111-111111111111' }
        $SyntheticLhId = '22222222-2222-4222-8222-222222222222'
        $SyntheticEnvId = '33333333-3333-4333-8333-333333333333'
        $SyntheticSmId = '44444444-4444-4444-8444-444444444444'

        $NbPayloadPath = Join-Path $TempDir 'notebook-payload.json'
        $SmPayloadPath = Join-Path $TempDir 'semantic-model-payload.json'
        $RptPayloadPath = Join-Path $TempDir 'report-payload.json'

        & node $NotebookBuilder --workspace-id $SyntheticWsId --lakehouse-id $SyntheticLhId `
            --lakehouse-name $LakehouseName --environment-id $SyntheticEnvId `
            --display-name $NotebookName --out $NbPayloadPath --force
        if ($LASTEXITCODE -ne 0) { throw 'Notebook payload validation failed.' }

        & node $SemanticModelBuilder --workspace-id $SyntheticWsId --lakehouse-id $SyntheticLhId `
            --out $SmPayloadPath
        if ($LASTEXITCODE -ne 0) { throw 'Semantic model payload validation failed.' }

        & node $ReportBuilder --semantic-model-id $SyntheticSmId --display-name $ReportName `
            --out $RptPayloadPath --force
        if ($LASTEXITCODE -ne 0) { throw 'Report payload validation failed.' }

        $Summary = [ordered]@{
            mode                  = 'dry-run'
            workspace             = if ($WorkspaceName) { $WorkspaceName } else { $SyntheticWsId }
            folderName            = $FolderName
            lakehouseName         = $LakehouseName
            environmentName       = $EnvironmentName
            wheel                 = $ResolvedWheel
            notebookName          = $NotebookName
            schemaBootstrap       = (-not $SkipSchemaBootstrap)
            semanticModelName     = $SemanticModelName
            reportName            = $ReportName
            deployFabricApp       = (-not $SkipFabricApp -and (Test-Path -LiteralPath $FabricAppDir))
            payloadPartsValidated = $true
        }
        if (-not [string]::IsNullOrWhiteSpace($OutputSummaryPath)) {
            $Summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $OutputSummaryPath -Encoding utf8
        }
        Write-Host ($Summary | ConvertTo-Json -Depth 10)
        return
    }

    $Token = Get-FabricAccessToken -AllowAzCliFallback -UseAzCli:$UseAzCli
    $Workspace = Resolve-TargetWorkspace -Name $WorkspaceName -Id $WorkspaceId `
        -Create:$CreateWorkspace -Capacity $CapacityId -Token $Token
    $WsId = $Workspace.id
    Write-Host "Target workspace: $($Workspace.displayName) ($WsId)"

    # 0. Folder (optional, defaults to 'FEMA')
    $Folder = if (-not [string]::IsNullOrWhiteSpace($FolderName)) {
        Resolve-OrCreateFolderPath -WorkspaceGuid $WsId -FolderPath $FolderName -Token $Token
    }
    else {
        $null
    }
    $FolderId = if ($Folder) { $Folder.id } else { $null }
    if ($Folder) {
        Write-Host "Folder ($($Folder.action)): $($Folder.displayName) ($FolderId)"
    }

    # 1. Lakehouse
    $Lakehouse = Resolve-OrCreateSimpleItem -WorkspaceGuid $WsId -Collection 'lakehouses' `
        -DisplayName $LakehouseName `
        -Description 'Governed Lakehouse storing staged ETL intake files and normalized assessment Delta tables.' `
        -FolderId $FolderId -SkillName 'onelake-catalog-cli' -Token $Token
    Write-Host "Lakehouse ($($Lakehouse.action)): $($Lakehouse.displayName) ($($Lakehouse.id))"

    # 2. Environment + Runtime 2.0 + Wheel + External Libraries + Publish
    $Environment = Resolve-OrCreateSimpleItem -WorkspaceGuid $WsId -Collection 'environments' `
        -DisplayName $EnvironmentName `
        -Description 'Fabric Runtime 2.0 (Python 3.13) environment with ETL Migration Accelerator wheel.' `
        -FolderId $FolderId -SkillName 'spark-cli' -Token $Token
    Write-Host "Environment ($($Environment.action)): $($Environment.displayName) ($($Environment.id))"

    if (-not $SkipEnvironmentPublish) {
        $null = Wait-EnvironmentIdle -WorkspaceGuid $WsId -EnvironmentId $Environment.id -Token $Token

        $SparkComputeBody = @{ runtimeVersion = '2.0' } | ConvertTo-Json -Compress
        $null = Invoke-FabricRequest -Method Patch `
            -Uri "$FabricApi/workspaces/$WsId/environments/$($Environment.id)/staging/sparkcompute?beta=false" `
            -Token $Token -SkillName 'spark-cli' -Body $SparkComputeBody

        try {
            $StagedLibs = Invoke-FabricRequest -Method Get `
                -Uri "$FabricApi/workspaces/$WsId/environments/$($Environment.id)/staging/libraries" `
                -Token $Token -SkillName 'spark-cli'
        }
        catch {
            if ($_.Exception.Message -notmatch '"errorCode":"EnvironmentLibrariesNotFound"') {
                throw
            }
            $StagedLibs = [pscustomobject]@{
                customLibraries = [pscustomobject]@{ wheelFiles = @() }
            }
            Write-Host 'Environment has no staged libraries yet; uploading the requested libraries.'
        }
        $DesiredWheelNames = @($ResolvedWheels | ForEach-Object { [IO.Path]::GetFileName($_) })
        foreach ($ExistingWheel in @($StagedLibs.customLibraries.wheelFiles)) {
            $NameStr = [string]$ExistingWheel
            if ([string]::IsNullOrWhiteSpace($NameStr)) { continue }
            $IsLegacyMonolith = $NameStr -like 'fabric_etl_migration_accelerator-*.whl'
            $IsSupersededWorkspaceWheel = (
                $NameStr -match '^(etl_migration_core|etl_portfolio_assessment|etl_target_fabric)-.*\.whl$' -and
                $NameStr -notin $DesiredWheelNames
            )
            if ($IsLegacyMonolith -or $IsSupersededWorkspaceWheel) {
                $EncodedLib = [Uri]::EscapeDataString($NameStr)
                $null = Invoke-FabricRequest -Method Delete `
                    -Uri "$FabricApi/workspaces/$WsId/environments/$($Environment.id)/staging/libraries?libraryToDelete=$EncodedLib" `
                    -Token $Token -SkillName 'spark-cli'
            }
        }

        foreach ($WheelArtifact in $ResolvedWheels) {
            $WheelFileName = [IO.Path]::GetFileName($WheelArtifact)
            $null = Invoke-FabricFileUpload `
                -Uri "$FabricApi/workspaces/$WsId/environments/$($Environment.id)/staging/libraries/$WheelFileName" `
                -FilePath $WheelArtifact -Token $Token -SkillName 'spark-cli' -Mode OctetStream
        }

        $null = Invoke-FabricFileUpload `
            -Uri "$FabricApi/workspaces/$WsId/environments/$($Environment.id)/staging/libraries/importExternalLibraries" `
            -FilePath $EnvironmentYmlPath -Token $Token -SkillName 'spark-cli' -Mode OctetStream

        $null = Invoke-FabricRequest -Method Post `
            -Uri "$FabricApi/workspaces/$WsId/environments/$($Environment.id)/staging/publish?beta=false" `
            -Token $Token -SkillName 'spark-cli'

        $FinalState = Wait-EnvironmentIdle -WorkspaceGuid $WsId -EnvironmentId $Environment.id -Token $Token
        if ($FinalState -ne 'Success') {
            throw "Environment publish ended in state '$FinalState' for $($Environment.id)."
        }
        $UploadedNames = ($ResolvedWheels | ForEach-Object { [IO.Path]::GetFileName($_) }) -join ', '
        Write-Host "Environment published successfully (Runtime 2.0 + $UploadedNames)."
    }

    # 3. Assessment Notebook bound to Lakehouse + Environment
    $NbPayloadPath = Join-Path $TempDir 'notebook-payload.json'
    & node $NotebookBuilder --workspace-id $WsId --lakehouse-id $Lakehouse.id `
        --lakehouse-name $Lakehouse.displayName --environment-id $Environment.id `
        --display-name $NotebookName --out $NbPayloadPath --force
    if ($LASTEXITCODE -ne 0) { throw 'Failed to build notebook payload.' }

    $Notebook = Upsert-DefinedItem -WorkspaceGuid $WsId -Collection 'notebooks' `
        -DisplayName $NotebookName -PayloadPath $NbPayloadPath -FolderId $FolderId -SkillName 'spark-cli' -Token $Token
    Write-Host "Notebook ($($Notebook.action)): $($Notebook.displayName) ($($Notebook.id))"

    # 4. Schema-on-first-deploy (idempotent 8-table Delta initialization)
    if (-not $SkipSchemaBootstrap) {
        $BootstrapBody = @{
            parameters = @(
                @{ name = 'INITIALIZE_SCHEMA_ONLY'; value = $true; type = 'Boolean' }
                @{ name = 'PERSIST_DELTA_TABLES'; value = $false; type = 'Boolean' }
                @{ name = 'CONFIRM_ASSESSMENT'; value = $false; type = 'Boolean' }
                @{ name = 'WRITE_REPORTS'; value = $false; type = 'Boolean' }
            )
        } | ConvertTo-Json -Depth 5 -Compress
        $JobResult = Invoke-FabricRequest -Method Post `
            -Uri "$FabricApi/workspaces/$WsId/notebooks/$($Notebook.id)/jobs/execute/instances?beta=false" `
            -Token $Token -SkillName 'spark-cli' -Body $BootstrapBody
        Write-Host "Schema bootstrap notebook run status: $($JobResult.status)"
    }

    # 5. Direct Lake Semantic Model bound to Workspace + Lakehouse
    $LakehouseDetails = Invoke-FabricRequest -Method Get `
        -Uri "$FabricApi/workspaces/$WsId/lakehouses/$($Lakehouse.id)" `
        -Token $Token -SkillName 'onelake-catalog-cli'
    $DefaultSchema = [string]$LakehouseDetails.properties.defaultSchema

    $SmPayloadPath = Join-Path $TempDir 'semantic-model-payload.json'
    if ([string]::IsNullOrWhiteSpace($DefaultSchema)) {
        & node $SemanticModelBuilder --workspace-id $WsId --lakehouse-id $Lakehouse.id `
            --display-name $SemanticModelName --no-schema --force --out $SmPayloadPath
    }
    else {
        & node $SemanticModelBuilder --workspace-id $WsId --lakehouse-id $Lakehouse.id `
            --display-name $SemanticModelName --schema-name $DefaultSchema --force --out $SmPayloadPath
    }
    if ($LASTEXITCODE -ne 0) { throw 'Failed to build semantic model payload.' }

    $SemanticModel = Upsert-DefinedItem -WorkspaceGuid $WsId -Collection 'semanticModels' `
        -DisplayName $SemanticModelName -PayloadPath $SmPayloadPath -FolderId $FolderId -SkillName 'semantic-model-authoring' -Token $Token
    Write-Host "Semantic Model ($($SemanticModel.action)): $($SemanticModel.displayName) ($($SemanticModel.id))"

    # Trigger a Direct Lake framing refresh so tables are immediately queryable
    $PbiToken = Get-FabricAccessToken -AllowAzCliFallback -UseAzCli:$UseAzCli `
        -Resource 'https://analysis.windows.net/powerbi/api'
    $RefreshBody = @{ notifyOption = 'NoNotification' } | ConvertTo-Json -Compress
    $null = Invoke-FabricRequest -Method Post `
        -Uri "https://api.powerbi.com/v1.0/myorg/groups/$WsId/datasets/$($SemanticModel.id)/refreshes" `
        -Token $PbiToken -SkillName 'semantic-model-authoring' -Body $RefreshBody -NoLroPoll
    for ($RefreshAttempt = 0; $RefreshAttempt -lt 30; $RefreshAttempt++) {
        Start-Sleep -Seconds 3
        $RefreshHistory = Invoke-FabricRequest -Method Get `
            -Uri "https://api.powerbi.com/v1.0/myorg/groups/$WsId/datasets/$($SemanticModel.id)/refreshes?`$top=1" `
            -Token $PbiToken -SkillName 'semantic-model-authoring'
        $LatestRefresh = @($RefreshHistory.value) | Select-Object -First 1
        if ($null -eq $LatestRefresh) { continue }
        if ($LatestRefresh.status -eq 'Completed') {
            Write-Host 'Semantic Model Direct Lake framing refresh completed.'
            break
        }
        if ($LatestRefresh.status -in @('Failed', 'Cancelled', 'Disabled')) {
            throw "Semantic Model refresh ended in $($LatestRefresh.status): $($LatestRefresh.serviceExceptionJson)"
        }
    }

    # 6. Power BI Report bound to Semantic Model
    $RptPayloadPath = Join-Path $TempDir 'report-payload.json'
    & node $ReportBuilder --semantic-model-id $SemanticModel.id --display-name $ReportName `
        --out $RptPayloadPath --force
    if ($LASTEXITCODE -ne 0) { throw 'Failed to build Power BI report payload.' }

    $Report = Upsert-DefinedItem -WorkspaceGuid $WsId -Collection 'reports' `
        -DisplayName $ReportName -PayloadPath $RptPayloadPath -FolderId $FolderId -SkillName 'powerbi-report-cli' -Token $Token
    $ReportUrl = "https://app.fabric.microsoft.com/groups/$WsId/reports/$($Report.id)"
    Write-Host "Power BI Report ($($Report.action)): $($Report.displayName) ($($Report.id))"

    # 7. Fabric Analyst App (rayfin)
    $FabricAppDeployed = $false
    $FabricAppId = $null
    if (-not $SkipFabricApp -and (Test-Path -LiteralPath $FabricAppDir -PathType Container)) {
        $null = Restore-RecordedFabricAppIfRecoverable `
            -WorkspaceGuid $WsId -WorkspaceName $Workspace.displayName `
            -AppDirectory $FabricAppDir -AppName $FabricAppName -Token $Token
        Push-Location $FabricAppDir
        try {
            $env:FABRIC_WORKSPACE_ID = $WsId
            $env:FABRIC_SEMANTIC_MODEL_ID = $SemanticModel.id
            $env:VITE_REPORT_URL = $ReportUrl

            & npm run build:fabric
            if ($LASTEXITCODE -ne 0) { throw 'Fabric app build failed.' }
            & npm --prefix rayfin/functions run build
            if ($LASTEXITCODE -ne 0) { throw 'Fabric app functions build failed.' }

            & npx rayfin up --workspace $Workspace.displayName --item-name $FabricAppName --yes
            if ($LASTEXITCODE -ne 0) { throw 'npx rayfin up failed.' }

            $WsId | & npx rayfin secret set FABRIC_WORKSPACE_ID --stdin
            if ($LASTEXITCODE -ne 0) { throw 'Failed to set FABRIC_WORKSPACE_ID secret.' }
            $Lakehouse.id | & npx rayfin secret set FABRIC_LAKEHOUSE_ID --stdin
            if ($LASTEXITCODE -ne 0) { throw 'Failed to set FABRIC_LAKEHOUSE_ID secret.' }
            $Notebook.id | & npx rayfin secret set FABRIC_NOTEBOOK_ID --stdin
            if ($LASTEXITCODE -ne 0) { throw 'Failed to set FABRIC_NOTEBOOK_ID secret.' }

            $ConfirmKey = if (-not [string]::IsNullOrWhiteSpace($env:DEPLOYMENT_CONFIRMATION_KEY)) {
                $env:DEPLOYMENT_CONFIRMATION_KEY
            }
            else {
                New-RandomSecretHex
            }
            $ConfirmKey | & npx rayfin secret set DEPLOYMENT_CONFIRMATION_KEY --stdin
            if ($LASTEXITCODE -ne 0) { throw 'Failed to set DEPLOYMENT_CONFIRMATION_KEY secret.' }

            $DeploymentsPath = Join-Path $FabricAppDir 'rayfin/.deployments.json'
            if (Test-Path -LiteralPath $DeploymentsPath -PathType Leaf) {
                $DeployRegistry = Get-Content -LiteralPath $DeploymentsPath -Raw | ConvertFrom-Json
                $ActiveKey = [string]$DeployRegistry.active
                if ($ActiveKey -and $DeployRegistry.deployments.$ActiveKey) {
                    $FabricAppId = [string]$DeployRegistry.deployments.$ActiveKey.fabricItemId
                }
            }
            if (-not [string]::IsNullOrWhiteSpace($FolderId) -and -not [string]::IsNullOrWhiteSpace($FabricAppId)) {
                try {
                    Move-ItemToFolderIfNeeded -WorkspaceGuid $WsId -ItemId $FabricAppId `
                        -CurrentFolderId '' -TargetFolderId $FolderId -Token $Token
                }
                catch {
                    Write-Warning "Could not move AppBackend item $FabricAppId into folder '$FolderName': $($_.Exception.Message)"
                }
            }

            $FabricAppDeployed = $true
            Write-Host 'Fabric Analyst App deployed and configured.'
        }
        finally {
            Pop-Location
        }
    }

    $Summary = [ordered]@{
        mode              = 'deployed'
        workspaceId       = $WsId
        workspaceName     = $Workspace.displayName
        folderId          = $FolderId
        folderName        = $FolderName
        lakehouseId       = $Lakehouse.id
        environmentId     = $Environment.id
        notebookId        = $Notebook.id
        semanticModelId   = $SemanticModel.id
        reportId          = $Report.id
        reportUrl         = $ReportUrl
        fabricAppId       = $FabricAppId
        fabricAppDeployed = $FabricAppDeployed
    }
    if (-not [string]::IsNullOrWhiteSpace($OutputSummaryPath)) {
        $Summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $OutputSummaryPath -Encoding utf8
    }
    Write-Host ($Summary | ConvertTo-Json -Depth 10)
}
finally {
    if (Test-Path -LiteralPath $TempDir) {
        Remove-Item -LiteralPath $TempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
