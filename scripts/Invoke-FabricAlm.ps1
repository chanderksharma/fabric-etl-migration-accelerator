#!/usr/bin/env pwsh
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
#Requires -Version 7.0

<#
.SYNOPSIS
    Synchronizes an authoritative Fabric workspace to Git or promotes pipeline stages.
.DESCRIPTION
    Commits validated Development workspace changes to its connected Git branch,
    promotes adjacent Fabric Deployment Pipeline stages, and optionally selects
    the target workspace's active Variable Library value set.
.PARAMETER Operation
    SyncDevelopmentToGit or Promote.
.PARAMETER WorkspaceId
    Development workspace ID used by SyncDevelopmentToGit.
.PARAMETER DeploymentPipelineId
    Fabric Deployment Pipeline ID used by Promote.
.PARAMETER SourceStageName
    Source deployment stage display name.
.PARAMETER TargetStageName
    Adjacent target deployment stage display name.
.PARAMETER VariableLibraryName
    Optional Variable Library display name in the affected workspace.
.PARAMETER ActiveValueSetName
    Optional active value set selected after synchronization or promotion.
.PARAMETER CommitComment
    Git commit comment, limited to 300 UTF-16 code units.
.PARAMETER DeploymentNote
    Deployment Pipeline operation note, limited to 1024 characters.
.PARAMETER DeploymentPlanId
    Optional preview Deployment Plan item ID.
.PARAMETER EnablePreviewDeploymentPlan
    Explicitly enables the beta Deployment Plan request contract.
.PARAMETER DryRun
    Validates configuration and prints the planned operation without calling Fabric.
.EXAMPLE
    ./scripts/Invoke-FabricAlm.ps1 -Operation SyncDevelopmentToGit `
        -WorkspaceId $env:FABRIC_WORKSPACE_ID
.EXAMPLE
    ./scripts/Invoke-FabricAlm.ps1 -Operation Promote `
        -DeploymentPipelineId $env:FABRIC_DEPLOYMENT_PIPELINE_ID `
        -SourceStageName Development -TargetStageName Test
.NOTES
    Git synchronization treats the Fabric Development workspace as authoritative,
    but fails closed when remote-only changes or conflicts are detected.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('SyncDevelopmentToGit', 'Promote')]
    [string]$Operation,

    [Parameter(Mandatory = $false)]
    [string]$WorkspaceId = $env:FABRIC_WORKSPACE_ID,

    [Parameter(Mandatory = $false)]
    [string]$DeploymentPipelineId = $env:FABRIC_DEPLOYMENT_PIPELINE_ID,

    [Parameter(Mandatory = $false)]
    [string]$SourceStageName = $env:FABRIC_SOURCE_STAGE_NAME,

    [Parameter(Mandatory = $false)]
    [string]$TargetStageName = $env:FABRIC_TARGET_STAGE_NAME,

    [Parameter(Mandatory = $false)]
    [string]$VariableLibraryName = $env:FABRIC_VARIABLE_LIBRARY_NAME,

    [Parameter(Mandatory = $false)]
    [string]$ActiveValueSetName = $env:FABRIC_ACTIVE_VALUE_SET_NAME,

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$CommitComment = 'Sync accelerator-generated Fabric items',

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$DeploymentNote = 'Promote validated accelerator-generated Fabric items',

    [Parameter(Mandatory = $false)]
    [string]$DeploymentPlanId = $env:FABRIC_DEPLOYMENT_PLAN_ID,

    [Parameter(Mandatory = $false)]
    [switch]$EnablePreviewDeploymentPlan,

    [Parameter(Mandatory = $false)]
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$FabricApi = 'https://api.fabric.microsoft.com/v1'

Import-Module (Join-Path $PSScriptRoot 'FabricApi.psm1') -Force

#region Functions

function Assert-FabricGuid {
    <#
    .SYNOPSIS
        Validates a required Fabric resource ID.
    .OUTPUTS
        None.
    #>
    [CmdletBinding()]
    [OutputType([void])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Value
    )

    $Parsed = [guid]::Empty
    if (-not [guid]::TryParse($Value, [ref]$Parsed) -or $Parsed -eq [guid]::Empty) {
        throw "$Name must be a non-empty GUID"
    }
}

function Get-FabricGitStatus {
    <#
    .SYNOPSIS
        Reads the current Git synchronization status for a workspace.
    .OUTPUTS
        PSCustomObject Git status response.
    #>
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Workspace,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Token
    )

    return Invoke-FabricRequest -Method Get `
        -Uri "$FabricApi/workspaces/$Workspace/git/status" `
        -Token $Token -SkillName 'git-integration-operations-cli' -FetchResult
}

function Set-FabricVariableLibraryValueSet {
    <#
    .SYNOPSIS
        Selects and verifies a Variable Library active value set.
    .OUTPUTS
        PSCustomObject activation result.
    #>
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Workspace,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$LibraryName,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$ValueSetName,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Token
    )

    $Libraries = @()
    $NextUri = "$FabricApi/workspaces/$Workspace/items?type=VariableLibrary"
    while (-not [string]::IsNullOrWhiteSpace($NextUri)) {
        $Page = Invoke-FabricRequest -Method Get -Uri $NextUri -Token $Token `
            -SkillName 'variable-library-cli'
        $Libraries += @(
            $Page.value | Where-Object {
                $_.type -eq 'VariableLibrary' -and $_.displayName -eq $LibraryName
            }
        )
        $NextUri = [string]$Page.continuationUri
    }
    if ($Libraries.Count -ne 1) {
        throw "Expected one Variable Library named '$LibraryName', found $($Libraries.Count)"
    }

    $LibraryId = [string]$Libraries[0].id
    $Body = @{
        properties = @{ activeValueSetName = $ValueSetName }
    } | ConvertTo-Json -Depth 5 -Compress
    $Uri = "$FabricApi/workspaces/$Workspace/variableLibraries/$LibraryId"
    $null = Invoke-FabricRequest -Method Patch -Uri $Uri -Token $Token `
        -SkillName 'variable-library-cli' -Body $Body
    $Verified = Invoke-FabricRequest -Method Get -Uri $Uri -Token $Token `
        -SkillName 'variable-library-cli'
    if ([string]$Verified.properties.activeValueSetName -ne $ValueSetName) {
        throw "Variable Library '$LibraryName' did not activate value set '$ValueSetName'"
    }

    return [pscustomobject]@{
        LibraryName = $LibraryName
        ValueSetName = $ValueSetName
        Status       = 'Activated'
    }
}

function Sync-FabricDevelopmentToGit {
    <#
    .SYNOPSIS
        Commits authoritative Development workspace changes to Git.
    .OUTPUTS
        PSCustomObject synchronization result.
    #>
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Workspace,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Comment,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Token
    )

    $CommentLength = [Text.Encoding]::Unicode.GetByteCount($Comment) / 2
    if ($CommentLength -gt 300) {
        throw 'CommitComment must be 300 UTF-16 code units or fewer'
    }

    $Status = Get-FabricGitStatus -Workspace $Workspace -Token $Token
    $Changes = @($Status.changes)
    $Conflicts = @($Changes | Where-Object conflictType -eq 'Conflict')
    if ($Conflicts.Count -gt 0) {
        throw 'Fabric Git status contains conflicts; reconcile them before committing'
    }
    $RemoteChanges = @(
        $Changes | Where-Object {
            -not [string]::IsNullOrWhiteSpace([string]$_.remoteChange)
        }
    )
    if ($RemoteChanges.Count -gt 0) {
        throw 'Fabric Git status contains remote changes; update or reconcile the workspace first'
    }
    if ($Changes.Count -eq 0) {
        if ([string]$Status.workspaceHead -ne [string]$Status.remoteCommitHash) {
            throw 'Fabric Git heads differ even though no committable workspace changes were returned'
        }
        return [pscustomobject]@{
            Operation   = 'SyncDevelopmentToGit'
            Status      = 'NoChanges'
            ChangeCount = 0
        }
    }
    if ([string]::IsNullOrWhiteSpace([string]$Status.workspaceHead)) {
        throw 'Fabric Git status did not return workspaceHead'
    }

    $Body = @{
        mode          = 'All'
        workspaceHead = [string]$Status.workspaceHead
        comment       = $Comment
    } | ConvertTo-Json -Depth 5 -Compress
    $null = Invoke-FabricRequest -Method Post `
        -Uri "$FabricApi/workspaces/$Workspace/git/commitToGit" `
        -Token $Token -SkillName 'git-integration-operations-cli' -Body $Body

    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
        $Verified = Get-FabricGitStatus -Workspace $Workspace -Token $Token
        if (
            [string]$Verified.workspaceHead -eq [string]$Verified.remoteCommitHash -and
            @($Verified.changes).Count -eq 0
        ) {
            return [pscustomobject]@{
                Operation   = 'SyncDevelopmentToGit'
                Status      = 'Committed'
                ChangeCount = $Changes.Count
            }
        }
        Start-Sleep -Seconds 8
    }
    throw 'Fabric Git synchronization did not converge after commitToGit completed'
}

function Get-FabricDeploymentStages {
    <#
    .SYNOPSIS
        Lists every stage in a Fabric Deployment Pipeline.
    .OUTPUTS
        PSCustomObject deployment stages.
    #>
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$PipelineId,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Token
    )

    $NextUri = "$FabricApi/deploymentPipelines/$PipelineId/stages"
    while (-not [string]::IsNullOrWhiteSpace($NextUri)) {
        $Page = Invoke-FabricRequest -Method Get -Uri $NextUri -Token $Token `
            -SkillName 'deployment-pipelines-authoring-cli'
        foreach ($Stage in @($Page.value)) {
            $Stage
        }
        $NextUri = [string]$Page.continuationUri
    }
}

function Resolve-FabricDeploymentStage {
    <#
    .SYNOPSIS
        Resolves exactly one Deployment Pipeline stage by display name.
    .OUTPUTS
        PSCustomObject deployment stage.
    #>
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject[]]$Stages,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$DisplayName
    )

    $Matches = @($Stages | Where-Object displayName -eq $DisplayName)
    if ($Matches.Count -ne 1) {
        throw "Expected one Deployment Pipeline stage named '$DisplayName', found $($Matches.Count)"
    }
    return $Matches[0]
}

function Invoke-FabricStagePromotion {
    <#
    .SYNOPSIS
        Promotes all supported items between adjacent deployment stages.
    .OUTPUTS
        PSCustomObject promotion result.
    #>
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$PipelineId,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$SourceName,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$TargetName,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Note,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Token,

        [Parameter(Mandatory = $false)]
        [string]$PlanId,

        [Parameter(Mandatory = $false)]
        [switch]$UsePreviewPlan,

        [Parameter(Mandatory = $false)]
        [string]$LibraryName,

        [Parameter(Mandatory = $false)]
        [string]$ValueSetName
    )

    if ($Note.Length -gt 1024) {
        throw 'DeploymentNote must be 1024 characters or fewer'
    }
    $Stages = @(Get-FabricDeploymentStages -PipelineId $PipelineId -Token $Token)
    $Source = Resolve-FabricDeploymentStage -Stages $Stages -DisplayName $SourceName
    $Target = Resolve-FabricDeploymentStage -Stages $Stages -DisplayName $TargetName
    if ([int]$Target.order -ne ([int]$Source.order + 1)) {
        throw 'Promotion requires adjacent forward Deployment Pipeline stages'
    }
    if ([string]::IsNullOrWhiteSpace([string]$Source.workspaceId)) {
        throw "Source stage '$SourceName' has no assigned workspace"
    }
    if ([string]::IsNullOrWhiteSpace([string]$Target.workspaceId)) {
        throw "Target stage '$TargetName' has no assigned workspace"
    }

    $BodyObject = @{
        sourceStageId = [string]$Source.id
        targetStageId = [string]$Target.id
        note          = $Note
    }
    $DeployUri = "$FabricApi/deploymentPipelines/$PipelineId/deploy"
    if (-not [string]::IsNullOrWhiteSpace($PlanId)) {
        if (-not $UsePreviewPlan) {
            throw 'EnablePreviewDeploymentPlan is required when DeploymentPlanId is set'
        }
        $BodyObject.options = @{
            deploymentPlan = @{
                referenceType = 'ByItemId'
                itemId        = $PlanId
            }
        }
        $DeployUri += '?beta=true'
    }
    elseif ($UsePreviewPlan) {
        throw 'DeploymentPlanId is required when EnablePreviewDeploymentPlan is set'
    }

    $null = Invoke-FabricRequest -Method Post -Uri $DeployUri -Token $Token `
        -SkillName 'deployment-pipelines-authoring-cli' `
        -Body ($BodyObject | ConvertTo-Json -Depth 10 -Compress)

    $VariableResult = $null
    if (-not [string]::IsNullOrWhiteSpace($LibraryName)) {
        $VariableResult = Set-FabricVariableLibraryValueSet `
            -Workspace ([string]$Target.workspaceId) -LibraryName $LibraryName `
            -ValueSetName $ValueSetName -Token $Token
    }
    return [pscustomobject]@{
        Operation       = 'Promote'
        Status          = 'Succeeded'
        SourceStage     = $SourceName
        TargetStage     = $TargetName
        VariableLibrary = $VariableResult
    }
}

function Write-FabricAlmSummary {
    <#
    .SYNOPSIS
        Writes an ALM result to the GitHub step summary.
    .OUTPUTS
        None.
    #>
    [CmdletBinding()]
    [OutputType([void])]
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Result
    )

    if ([string]::IsNullOrWhiteSpace($env:GITHUB_STEP_SUMMARY)) {
        return
    }
    $Rows = @(
        '# Fabric ALM operation'
        ''
        "* Operation: ``$($Result.Operation)``"
        "* Status: ``$($Result.Status)``"
    )
    if ($Result.SourceStage) {
        $Rows += "* Promotion: ``$($Result.SourceStage)`` to ``$($Result.TargetStage)``"
    }
    $Rows += ''
    Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Value $Rows -Encoding utf8
}

#endregion Functions

#region Main Execution

if ($MyInvocation.InvocationName -ne '.') {
    try {
        if (
            [string]::IsNullOrWhiteSpace($VariableLibraryName) -xor
            [string]::IsNullOrWhiteSpace($ActiveValueSetName)
        ) {
            throw 'VariableLibraryName and ActiveValueSetName must be provided together'
        }

        if ($Operation -eq 'SyncDevelopmentToGit') {
            Assert-FabricGuid -Name 'WorkspaceId' -Value $WorkspaceId
            if ($DryRun) {
                $Result = [pscustomobject]@{
                    Operation = $Operation
                    Status    = 'WouldSync'
                }
            }
            else {
                $AccessToken = Get-FabricAccessToken
                if (-not [string]::IsNullOrWhiteSpace($VariableLibraryName)) {
                    $null = Set-FabricVariableLibraryValueSet -Workspace $WorkspaceId `
                        -LibraryName $VariableLibraryName `
                        -ValueSetName $ActiveValueSetName -Token $AccessToken
                }
                $Result = Sync-FabricDevelopmentToGit -Workspace $WorkspaceId `
                    -Comment $CommitComment -Token $AccessToken
            }
        }
        else {
            Assert-FabricGuid -Name 'DeploymentPipelineId' -Value $DeploymentPipelineId
            if (
                [string]::IsNullOrWhiteSpace($SourceStageName) -or
                [string]::IsNullOrWhiteSpace($TargetStageName)
            ) {
                throw 'SourceStageName and TargetStageName are required for Promote'
            }
            if (-not [string]::IsNullOrWhiteSpace($DeploymentPlanId)) {
                Assert-FabricGuid -Name 'DeploymentPlanId' -Value $DeploymentPlanId
            }
            if (
                -not [string]::IsNullOrWhiteSpace($DeploymentPlanId) -and
                -not $EnablePreviewDeploymentPlan
            ) {
                throw 'EnablePreviewDeploymentPlan is required when DeploymentPlanId is set'
            }
            if (
                $EnablePreviewDeploymentPlan -and
                [string]::IsNullOrWhiteSpace($DeploymentPlanId)
            ) {
                throw 'DeploymentPlanId is required when EnablePreviewDeploymentPlan is set'
            }
            if ($DryRun) {
                $Result = [pscustomobject]@{
                    Operation   = $Operation
                    Status      = 'WouldPromote'
                    SourceStage = $SourceStageName
                    TargetStage = $TargetStageName
                }
            }
            else {
                $AccessToken = Get-FabricAccessToken
                $Result = Invoke-FabricStagePromotion `
                    -PipelineId $DeploymentPipelineId `
                    -SourceName $SourceStageName -TargetName $TargetStageName `
                    -Note $DeploymentNote -Token $AccessToken `
                    -PlanId $DeploymentPlanId `
                    -UsePreviewPlan:$EnablePreviewDeploymentPlan `
                    -LibraryName $VariableLibraryName `
                    -ValueSetName $ActiveValueSetName
            }
        }

        Write-FabricAlmSummary -Result $Result
        $Result | ConvertTo-Json -Depth 10
    }
    catch {
        Write-Error -ErrorAction Continue "Fabric ALM operation failed: $($_.Exception.Message)"
        exit 1
    }
}

#endregion Main Execution
