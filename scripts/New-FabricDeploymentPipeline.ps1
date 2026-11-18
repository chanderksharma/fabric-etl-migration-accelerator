#!/usr/bin/env pwsh
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
#Requires -Version 7.0

<#
.SYNOPSIS
    Creates or reuses a Fabric deployment pipeline and optionally attaches existing workspaces.
.DESCRIPTION
    Resolves an exact display name across accessible deployment pipelines.
    Creates an ordered stage collection only when the name is absent, and verifies
    the persisted pipeline and stage names. Requested workspaces are assigned
    only to empty stages; existing assignments are never replaced.
.PARAMETER DisplayName
    Pipeline display name, limited to 256 characters.
.PARAMETER Description
    Description for a new pipeline, limited to 1024 characters.
.PARAMETER StageNames
    Ordered stage names. Defaults to Development, Test, and Production.
.PARAMETER WorkspaceNames
    Optional workspace names in stage order. Blank entries leave stages unchanged.
.PARAMETER OnWorkspaceConflict
    Behavior when a requested workspace is already assigned: Fail or Reuse.
.PARAMETER DryRun
    Previews creation and workspace assignments without calling a write API.
.EXAMPLE
    .\scripts\New-FabricDeploymentPipeline.ps1 -DisplayName 'Accelerator ALM' -DryRun
.NOTES
    The Fabric administrator must allow the service principal to create
    workspaces, connections, and deployment pipelines.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [ValidateLength(1, 256)]
    [string]$DisplayName,

    [Parameter(Mandatory = $false)]
    [ValidateLength(0, 1024)]
    [string]$Description = 'Fabric deployment pipeline managed by the accelerator',

    [Parameter(Mandatory = $false)]
    [ValidateCount(2, 10)]
    [string[]]$StageNames = @('Development', 'Test', 'Production'),

    [Parameter(Mandatory = $false)]
    [string[]]$WorkspaceNames,

    [Parameter(Mandatory = $false)]
    [ValidateSet('Fail', 'Reuse')]
    [string]$OnWorkspaceConflict = 'Fail',

    [Parameter(Mandatory = $false)]
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$FabricApi = 'https://api.fabric.microsoft.com/v1'

Import-Module (Join-Path $PSScriptRoot 'FabricApi.psm1') -Force

#region Functions

function Get-FabricProvisioningCollection {
    <#
    .SYNOPSIS
        Reads a complete pipeline or stage collection with pagination.
    .OUTPUTS
        PSCustomObject collection entries.
    #>
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri,

        [Parameter(Mandatory = $true)]
        [string]$Token
    )

    $NextUri = $Uri
    $Visited = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $CollectionUri = [uri]$Uri
    while (-not [string]::IsNullOrWhiteSpace($NextUri)) {
        $PageUri = [uri]$NextUri
        if (
            -not $PageUri.IsAbsoluteUri -or
            $PageUri.GetLeftPart([UriPartial]::Path) -cne $CollectionUri.GetLeftPart([UriPartial]::Path) -or
            $PageUri.UserInfo -or -not $Visited.Add($NextUri)
        ) {
            throw 'Fabric returned an invalid or repeated provisioning page URI'
        }
        $Page = Invoke-FabricRequest -Method Get -Uri $NextUri -Token $Token `
            -SkillName 'deployment-pipelines-authoring-cli'
        if ($null -eq $Page -or $Page.value -isnot [array]) {
            throw 'Fabric returned an invalid provisioning collection'
        }
        foreach ($Entry in @($Page.value)) {
            if (
                $Entry.displayName -isnot [string] -or
                [string]::IsNullOrWhiteSpace($Entry.displayName)
            ) {
                throw 'Fabric returned a provisioning entry without a display name'
            }
            $Entry
        }
        $NextUri = [string]$Page.continuationUri
    }
}

function Get-FabricProvisioningId {
    <#
    .SYNOPSIS
        Validates and normalizes a resource ID returned by Fabric.
    .OUTPUTS
        System.String canonical GUID.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param([string]$Value, [string]$Resource)

    $ParsedId = [guid]::Empty
    if (-not [guid]::TryParse($Value, [ref]$ParsedId) -or $ParsedId -eq [guid]::Empty) {
        throw "Fabric did not return a valid $Resource ID"
    }
    return $ParsedId.ToString()
}

function Get-FabricWorkspaceAssignmentPlan {
    <#
    .SYNOPSIS
        Resolves requested workspaces and rejects or reuses existing stage assignments.
    .OUTPUTS
        PSCustomObject containing resolved pipeline target and assignment entries.
    #>
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [string[]]$Names,
        [string[]]$Stages,
        [object[]]$Pipelines,
        [string]$PipelineId,
        [string]$Token,
        [ValidateSet('Fail', 'Reuse')]
        [string]$OnConflict = 'Fail',
        [bool]$CanReuseByWorkspace = $false
    )

    $Workspaces = @(Get-FabricProvisioningCollection -Uri "$FabricApi/workspaces?roles=Admin" -Token $Token)
    $Plan = @(
        for ($Index = 0; $Index -lt $Names.Count; $Index++) {
            $Name = $Names[$Index]
            if ([string]::IsNullOrWhiteSpace($Name)) { continue }
            $Candidates = @($Workspaces | Where-Object displayName -CEQ $Name)
            if ($Candidates.Count -ne 1 -or $Candidates[0].type -ne 'Workspace') {
                throw "Expected one regular workspace named '$Name' with Admin access; found $($Candidates.Count) name matches"
            }
            [pscustomobject]@{
                StageName = $Stages[$Index]
                WorkspaceName = $Name
                WorkspaceId = Get-FabricProvisioningId -Value $Candidates[0].id -Resource 'workspace'
                Status = 'WouldAssign'
            }
        }
    )
    $ByWorkspace = @{}
    $ByStage = @{}
    foreach ($Entry in $Plan) {
        if ($ByWorkspace.ContainsKey($Entry.WorkspaceId)) {
            throw "Workspace '$($Entry.WorkspaceName)' was requested for more than one stage"
        }
        $ByWorkspace[$Entry.WorkspaceId] = $Entry
        $ByStage[$Entry.StageName] = $Entry
    }
    $StagesByPipeline = @{}
    $WorkspaceMatches = @()
    foreach ($Pipeline in $Pipelines) {
        $Id = Get-FabricProvisioningId -Value $Pipeline.id -Resource 'deployment pipeline'
        $CurrentStages = @(Get-FabricProvisioningCollection `
            -Uri "$FabricApi/deploymentPipelines/$Id/stages" -Token $Token)
        $StagesByPipeline[$Id] = $CurrentStages
        foreach ($Stage in $CurrentStages) {
            if (-not $Stage.workspaceId) { continue }
            $WorkspaceId = Get-FabricProvisioningId -Value $Stage.workspaceId -Resource 'assigned workspace'
            if ($Id -eq $PipelineId -and $ByStage.ContainsKey($Stage.displayName)) {
                $Entry = $ByStage[$Stage.displayName]
                if ($Entry.WorkspaceId -ne $WorkspaceId) {
                    throw "Stage '$($Stage.displayName)' already has a different workspace; it will not be replaced"
                }
            }
            if ($ByWorkspace.ContainsKey($WorkspaceId)) {
                $Entry = $ByWorkspace[$WorkspaceId]
                $WorkspaceMatches += [pscustomobject]@{
                    PipelineId = $Id
                    PipelineName = [string]$Pipeline.displayName
                    StageName = [string]$Stage.displayName
                    Entry = $Entry
                }
            }
        }
    }

    $ReusedByWorkspace = $false
    $TargetPipelineId = $PipelineId
    $TargetDisplayName = ''
    $Conflicts = @($WorkspaceMatches | Where-Object {
        $_.PipelineId -ne $PipelineId -or $_.StageName -cne $_.Entry.StageName
    })
    if ($Conflicts.Count -gt 0) {
        if (-not $CanReuseByWorkspace -or $OnConflict -ne 'Reuse') {
            $First = $Conflicts[0]
            throw "Workspace '$($First.Entry.WorkspaceName)' is already assigned to '$($First.PipelineName)' / '$($First.StageName)'; it will not be moved"
        }
        $MatchedPipelineIds = @($WorkspaceMatches.PipelineId | Sort-Object -Unique)
        if ($MatchedPipelineIds.Count -gt 1) {
            $Details = ($WorkspaceMatches | ForEach-Object {
                "'$($_.Entry.WorkspaceName)' -> '$($_.PipelineName)' / '$($_.StageName)'"
            }) -join '; '
            throw "Requested workspaces are assigned to different pipelines ($Details); they will not be moved"
        }
        $WrongStage = @($WorkspaceMatches | Where-Object { $_.StageName -cne $_.Entry.StageName })
        if ($WrongStage.Count -gt 0) {
            $FirstWrong = $WrongStage[0]
            throw "Workspace '$($FirstWrong.Entry.WorkspaceName)' is assigned to '$($FirstWrong.PipelineName)' / '$($FirstWrong.StageName)', which does not match requested stage '$($FirstWrong.Entry.StageName)'; it will not be moved"
        }
        $TargetPipelineId = $MatchedPipelineIds[0]
        $TargetDisplayName = $WorkspaceMatches[0].PipelineName
        $ReusedByWorkspace = $true
        foreach ($Stage in $StagesByPipeline[$TargetPipelineId]) {
            if (-not $Stage.workspaceId -or -not $ByStage.ContainsKey($Stage.displayName)) { continue }
            $Entry = $ByStage[$Stage.displayName]
            $AssignedId = Get-FabricProvisioningId -Value $Stage.workspaceId -Resource 'assigned workspace'
            if ($Entry.WorkspaceId -ne $AssignedId) {
                throw "Stage '$($Stage.displayName)' in '$TargetDisplayName' already has a different workspace; it will not be replaced"
            }
        }
    }
    foreach ($Match in $WorkspaceMatches) {
        $Match.Entry.Status = 'AlreadyAssigned'
    }
    return [pscustomobject]@{
        ReusedByWorkspace = $ReusedByWorkspace
        PipelineId = $TargetPipelineId
        DisplayName = $TargetDisplayName
        Assignments = @($Plan)
    }
}

function Set-FabricProvisioningAssignments {
    <#
    .SYNOPSIS
        Attaches workspaces to empty stages and verifies each assignment.
    .OUTPUTS
        None.
    #>
    [CmdletBinding()]
    [OutputType([void])]
    param([object[]]$Plan, [object[]]$Stages, [string]$PipelineId, [string]$Token)

    $StageByName = @{}
    foreach ($Stage in $Stages) { $StageByName[$Stage.displayName] = $Stage }
    $StageUris = @{}
    foreach ($Entry in $Plan) {
        $Stage = $StageByName[$Entry.StageName]
        if ($Stage.workspaceId -eq $Entry.WorkspaceId) {
            $Entry.Status = 'AlreadyAssigned'
        }
        elseif ($Stage.workspaceId -or $Entry.Status -eq 'AlreadyAssigned') {
            throw "Stage '$($Entry.StageName)' assignment changed after preflight; run a new preview"
        }
        else {
            $StageId = Get-FabricProvisioningId -Value $Stage.id -Resource 'stage'
            $StageUris[$Entry.StageName] = "$FabricApi/deploymentPipelines/$PipelineId/stages/$StageId"
        }
    }
    foreach ($Entry in $Plan | Where-Object Status -EQ 'WouldAssign') {
        $StageUri = $StageUris[$Entry.StageName]
        try {
            $null = Invoke-FabricRequest -Method Post -Uri "$StageUri/assignWorkspace" -Token $Token `
                -SkillName 'deployment-pipelines-authoring-cli' `
                -Body (@{ workspaceId = $Entry.WorkspaceId } | ConvertTo-Json -Compress)
            $Current = Invoke-FabricRequest -Method Get -Uri $StageUri -Token $Token `
                -SkillName 'deployment-pipelines-authoring-cli'
            if ($Current.id -ne $StageByName[$Entry.StageName].id -or
                $Current.workspaceId -ne $Entry.WorkspaceId) {
                throw 'Workspace assignment could not be verified'
            }
            $Entry.Status = 'Assigned'
        }
        catch {
            throw "Assignment for stage '$($Entry.StageName)' in pipeline '$PipelineId' failed: $($_.Exception.Message). Earlier assignments are not rolled back; preview and rerun to resume."
        }
    }
}

function Write-FabricProvisioningSummary {
    <#
    .SYNOPSIS
        Records the provisioning result without exposing authentication material.
    .OUTPUTS
        None.
    #>
    [CmdletBinding()]
    [OutputType([void])]
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Result
    )

    if ([string]::IsNullOrWhiteSpace($env:GITHUB_STEP_SUMMARY)) { return }
    $Rows = @('# Fabric deployment pipeline provisioning'; '')
    foreach ($Field in @('Status', 'DisplayName', 'PipelineId')) {
        $Value = [Net.WebUtility]::HtmlEncode([string]$Result.$Field).
            Replace("`r", ' ').Replace("`n", ' ')
        $Rows += "* ${Field}: <code>$Value</code>"
    }
    $Rows += ''
    $Rows += 'Stages, in order:'
    foreach ($Name in $Result.StageNames) {
        $Value = [Net.WebUtility]::HtmlEncode([string]$Name)
        $Rows += "* <code>$Value</code>"
    }
    $Rows += ''
    $Rows += 'Workspace requests:'
    if ($Result.WorkspaceAssignments.Count -eq 0) { $Rows += '* None' }
    foreach ($Entry in $Result.WorkspaceAssignments) {
        $Assignment = [Net.WebUtility]::HtmlEncode(
            "$($Entry.StageName): $($Entry.WorkspaceName) ($($Entry.WorkspaceId)) - $($Entry.Status)"
        ).Replace("`r", ' ').Replace("`n", ' ')
        $Rows += "* <code>$Assignment</code>"
    }
    $Rows += 'No workspaces were created, moved, or unassigned. Repository variables were not modified.'
    Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Value $Rows -Encoding utf8
}

#endregion Functions

#region Main Execution

if ($MyInvocation.InvocationName -ne '.') {
    try {
        if (
            [string]::IsNullOrWhiteSpace($DisplayName) -or
            $DisplayName -cne $DisplayName.Trim()
        ) {
            throw 'DisplayName must be non-empty and have no leading or trailing whitespace'
        }
        $Seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        foreach ($Name in $StageNames) {
            if (
                [string]::IsNullOrWhiteSpace($Name) -or $Name.Length -gt 256 -or
                $Name -cne $Name.Trim() -or -not $Seen.Add($Name)
            ) {
                throw 'Stage names must be distinct, non-empty strings of at most 256 characters without surrounding whitespace'
            }
            if ($PSBoundParameters.ContainsKey('WorkspaceNames') -and $WorkspaceNames.Count -ne $StageNames.Count) {
                throw 'WorkspaceNames must contain one entry per stage; use blanks to leave stages unchanged'
            }
        }
        $Token = Get-FabricAccessToken
        $Pipelines = @(Get-FabricProvisioningCollection `
            -Uri "$FabricApi/deploymentPipelines" -Token $Token)
        $Matches = @($Pipelines | Where-Object displayName -CEQ $DisplayName)
        if ($Matches.Count -gt 1) {
            throw "More than one accessible pipeline has the exact name '$DisplayName'"
        }
        $PipelineId = ''
        $ResolvedDisplayName = $DisplayName
        $Status = 'WouldCreate'
        if ($Matches.Count -eq 1) {
            $PipelineId = Get-FabricProvisioningId -Value $Matches[0].id -Resource 'deployment pipeline'
            $Status = 'Reused'
        }
        $Assignments = @()
        if (@($WorkspaceNames | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count -gt 0) {
            $AssignmentPlan = Get-FabricWorkspaceAssignmentPlan -Names $WorkspaceNames `
                -Stages $StageNames -Pipelines $Pipelines -PipelineId $PipelineId -Token $Token `
                -OnConflict $OnWorkspaceConflict -CanReuseByWorkspace ($Status -eq 'WouldCreate')
            $Assignments = @($AssignmentPlan.Assignments)
            if ($AssignmentPlan.ReusedByWorkspace) {
                $PipelineId = $AssignmentPlan.PipelineId
                $ResolvedDisplayName = $AssignmentPlan.DisplayName
                $Status = 'Reused'
            }
        }
        if ($Status -eq 'WouldCreate' -and -not $DryRun) {
            $RequestedStages = @(
                for ($Index = 0; $Index -lt $StageNames.Count; $Index++) {
                    @{
                        displayName = $StageNames[$Index]
                        isPublic = ($Index -eq $StageNames.Count - 1)
                    }
                }
            )
            $Body = @{
                displayName = $ResolvedDisplayName
                description = $Description
                stages = $RequestedStages
            } | ConvertTo-Json -Depth 8 -Compress
            $Created = Invoke-FabricRequest -Method Post `
                -Uri "$FabricApi/deploymentPipelines" -Token $Token `
                -SkillName 'deployment-pipelines-authoring-cli' -Body $Body
            $PipelineId = Get-FabricProvisioningId -Value $Created.id -Resource 'deployment pipeline'
            $Status = 'Created'
        }
        if ($Status -ne 'WouldCreate') {
            $Pipeline = Invoke-FabricRequest -Method Get `
                -Uri "$FabricApi/deploymentPipelines/$PipelineId" -Token $Token `
                -SkillName 'deployment-pipelines-authoring-cli'
            if ($Pipeline.displayName -cne $ResolvedDisplayName -or $Pipeline.id -ne $PipelineId) {
                throw 'Pipeline identity did not match the requested display name and ID'
            }
            $Stages = @(Get-FabricProvisioningCollection `
                -Uri "$FabricApi/deploymentPipelines/$PipelineId/stages" -Token $Token |
                Sort-Object order)
            if ($Stages.Count -ne $StageNames.Count) {
                throw "Stage-count verification failed for pipeline '$PipelineId'; no pipeline was replaced or deleted"
            }
            for ($Index = 0; $Index -lt $StageNames.Count; $Index++) {
                if (
                    [int]$Stages[$Index].order -ne $Index -or
                    $Stages[$Index].displayName -cne $StageNames[$Index]
                ) {
                    throw "Stage names or order differ for pipeline '$PipelineId'; no pipeline was replaced or deleted"
                }
            }
            if (-not $DryRun -and $Assignments.Count -gt 0) {
                Set-FabricProvisioningAssignments -Plan $Assignments -Stages $Stages `
                    -PipelineId $PipelineId -Token $Token
            }
        }
        $Result = [pscustomobject]@{
            Status = $Status
            PipelineId = $PipelineId
            DisplayName = $ResolvedDisplayName
            StageNames = @($StageNames)
            WorkspaceAssignments = $Assignments
            DryRun = $DryRun.IsPresent
        }
        Write-FabricProvisioningSummary -Result $Result
        $Result | ConvertTo-Json -Depth 8
    }
    catch {
        $Detail = $_.Exception.Message
        if ($Detail -match 'Fabric request failed \(403\)') {
            $Detail += ' Verify pipeline and requested workspace Admin access, and ask a Fabric administrator to allow this service principal to create deployment pipelines.'
        }
        Write-Error -ErrorAction Continue "Fabric deployment pipeline provisioning failed: $Detail"
        exit 1
    }
}

#endregion Main Execution
