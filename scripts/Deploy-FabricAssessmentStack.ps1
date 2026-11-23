#!/usr/bin/env pwsh
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
#Requires -Version 7.0

<#
.SYNOPSIS
    Deploys the Fabric assessment notebook and analytics stack from prebuilt wheels.
.DESCRIPTION
    Validates a directory containing the three decoupled accelerator wheels, then
    invokes the idempotent workspace installer to create or update the Lakehouse,
    Fabric Runtime 2.0 Environment, portfolio assessment Notebook, eight Delta
    tables, Direct Lake Semantic Model, and Power BI Report. The Fabric Analyst
    App is deliberately excluded.
.PARAMETER WorkspaceName
    Target Fabric workspace display name.
.PARAMETER WorkspaceId
    Target Fabric workspace GUID. Use either WorkspaceName or WorkspaceId.
.PARAMETER WheelDirectory
    Directory containing etl-migration-core, etl-portfolio-assessment, and
    etl-target-fabric wheel files.
.PARAMETER CreateWorkspace
    Creates WorkspaceName on CapacityId when the workspace does not exist.
.PARAMETER CapacityId
    Fabric capacity GUID used with CreateWorkspace.
.PARAMETER FolderName
    Workspace folder path for the deployed items. Pass an empty string for root.
.PARAMETER LakehouseName
    Display name of the assessment Lakehouse.
.PARAMETER EnvironmentName
    Display name of the Fabric Runtime 2.0 Environment.
.PARAMETER NotebookName
    Display name of the portfolio assessment Notebook.
.PARAMETER SemanticModelName
    Display name of the Direct Lake Semantic Model.
.PARAMETER ReportName
    Display name of the Power BI Report.
.PARAMETER EnvironmentYmlPath
    Path to the external-library YAML uploaded to the Fabric Environment.
.PARAMETER SkipEnvironmentPublish
    Reuses the existing published Environment without uploading libraries.
.PARAMETER SkipSchemaBootstrap
    Skips the notebook run that initializes the eight Delta tables.
.PARAMETER UseAzCli
    Acquires the Fabric token from the current Azure CLI sign-in.
.PARAMETER OutputSummaryPath
    Optional path for the nonsecret deployment summary JSON.
.PARAMETER DryRun
    Validates wheels and definition payloads without changing Fabric.
.EXAMPLE
    pwsh -NoProfile -File scripts\Deploy-FabricAssessmentStack.ps1 `
      -WorkspaceName 'fabric-dev' -WheelDirectory .\dist -DryRun
.EXAMPLE
    pwsh -NoProfile -File scripts\Deploy-FabricAssessmentStack.ps1 `
      -WorkspaceName 'fabric-dev' -WheelDirectory .\dist -UseAzCli
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceName,

    [Parameter(Mandatory = $false)]
    [string]$WorkspaceId,

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$WheelDirectory = (Join-Path $PSScriptRoot '..\dist'),

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
    [string]$EnvironmentYmlPath = (Join-Path $PSScriptRoot 'fabric-environment.yml'),

    [Parameter(Mandatory = $false)]
    [switch]$SkipEnvironmentPublish,

    [Parameter(Mandatory = $false)]
    [switch]$SkipSchemaBootstrap,

    [Parameter(Mandatory = $false)]
    [switch]$UseAzCli,

    [Parameter(Mandatory = $false)]
    [string]$OutputSummaryPath,

    [Parameter(Mandatory = $false)]
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

#region Functions

function Resolve-AssessmentWheelDirectory {
    <#
    .SYNOPSIS
        Validates and resolves the three prebuilt assessment wheels.
    .OUTPUTS
        System.String containing the resolved wheel directory.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "WheelDirectory not found: $Path"
    }

    $ResolvedDirectory = (Resolve-Path -LiteralPath $Path).Path
    $RequiredPatterns = @(
        'etl_migration_core-*.whl'
        'etl_portfolio_assessment-*.whl'
        'etl_target_fabric-*.whl'
    )
    $Selected = foreach ($Pattern in $RequiredPatterns) {
        $Wheel = Get-ChildItem -LiteralPath $ResolvedDirectory -Filter $Pattern -File |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
        if (-not $Wheel) {
            throw "Required wheel missing from ${ResolvedDirectory}: $Pattern"
        }
        $Wheel
    }

    Write-Host 'Using prebuilt assessment wheels:'
    $Selected | ForEach-Object { Write-Host "  $($_.Name)" }
    return $ResolvedDirectory
}

function Invoke-FabricAssessmentStackDeployment {
    <#
    .SYNOPSIS
        Invokes the shared workspace installer for the assessment-only stack.
    .OUTPUTS
        None. Writes deployment progress and an optional summary file.
    #>
    [CmdletBinding()]
    [OutputType([void])]
    param()

    if (
        [string]::IsNullOrWhiteSpace($WorkspaceName) -and
        [string]::IsNullOrWhiteSpace($WorkspaceId)
    ) {
        throw 'Provide -WorkspaceName or -WorkspaceId.'
    }
    if (
        -not [string]::IsNullOrWhiteSpace($WorkspaceName) -and
        -not [string]::IsNullOrWhiteSpace($WorkspaceId)
    ) {
        throw 'Provide either -WorkspaceName or -WorkspaceId, not both.'
    }

    $ResolvedWheelDirectory = Resolve-AssessmentWheelDirectory -Path $WheelDirectory
    $Installer = Join-Path $PSScriptRoot 'Deploy-AcceleratorWorkspace.ps1'
    if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
        throw "Shared workspace installer not found: $Installer"
    }

    $Arguments = @{
        WheelPath             = $ResolvedWheelDirectory
        SkipWheelBuild        = $true
        SkipFabricApp         = $true
        FolderName            = $FolderName
        LakehouseName         = $LakehouseName
        EnvironmentName       = $EnvironmentName
        NotebookName          = $NotebookName
        SemanticModelName     = $SemanticModelName
        ReportName            = $ReportName
        EnvironmentYmlPath    = $EnvironmentYmlPath
        CreateWorkspace       = $CreateWorkspace
        CapacityId            = $CapacityId
        SkipEnvironmentPublish = $SkipEnvironmentPublish
        SkipSchemaBootstrap   = $SkipSchemaBootstrap
        UseAzCli              = $UseAzCli
        DryRun                = $DryRun
    }
    if (-not [string]::IsNullOrWhiteSpace($WorkspaceName)) {
        $Arguments.WorkspaceName = $WorkspaceName
    }
    if (-not [string]::IsNullOrWhiteSpace($WorkspaceId)) {
        $Arguments.WorkspaceId = $WorkspaceId
    }
    if (-not [string]::IsNullOrWhiteSpace($OutputSummaryPath)) {
        $Arguments.OutputSummaryPath = $OutputSummaryPath
    }

    & $Installer @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Assessment stack deployment failed with exit code $LASTEXITCODE."
    }
}

#endregion Functions

#region Main Execution

if ($MyInvocation.InvocationName -ne '.') {
    try {
        Invoke-FabricAssessmentStackDeployment
    }
    catch {
        Write-Error -ErrorAction Continue $_.Exception.Message
        exit 1
    }
}

#endregion Main Execution
