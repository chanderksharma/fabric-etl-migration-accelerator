#!/usr/bin/env pwsh
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
#Requires -Version 7.0

<#
.SYNOPSIS
    Synchronizes an authoritative Fabric workspace to Git or promotes pipeline stages.
.DESCRIPTION
    Commits validated Development workspace changes to its connected Git branch,
    plans and promotes explicit item scopes between adjacent deployment stages,
    and optionally activates a selected target Variable Library value set.
.PARAMETER Operation
    SyncDevelopmentToGit, PlanPromotion, or Promote.
.PARAMETER WorkspaceId
    Development workspace ID used by SyncDevelopmentToGit.
.PARAMETER DeploymentPipelineId
    Fabric Deployment Pipeline ID used by PlanPromotion and Promote.
.PARAMETER SourceStageName
    Source deployment stage display name.
.PARAMETER TargetStageName
    Adjacent target deployment stage display name.
.PARAMETER PromotionScope
    Selected by default, or All to explicitly include every supported source item.
.PARAMETER SelectedItemsJson
    JSON array of objects containing an exact item name and type.
.PARAMETER DependenciesReviewed
    Confirms that selected items include required dependencies or those dependencies exist in the target.
.PARAMETER ReviewedPlanJson
    Unmodified PlanPromotion JSON, required before a non-dry-run promotion.
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
    Validates configuration without calling Fabric; use PlanPromotion for read-only item resolution.
.EXAMPLE
    ./scripts/Invoke-FabricAlm.ps1 -Operation SyncDevelopmentToGit `
        -WorkspaceId $env:FABRIC_WORKSPACE_ID
.EXAMPLE
    ./scripts/Invoke-FabricAlm.ps1 -Operation PlanPromotion -PromotionScope All `
        -DeploymentPipelineId $env:FABRIC_DEPLOYMENT_PIPELINE_ID `
        -SourceStageName Development -TargetStageName Test
.NOTES
    Git synchronization treats the Fabric Development workspace as authoritative,
    but fails closed when remote-only changes or conflicts are detected.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('SyncDevelopmentToGit', 'PlanPromotion', 'Promote')]
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
    [ValidateSet('Selected', 'All')]
    [string]$PromotionScope = 'Selected',

    [Parameter(Mandatory = $false)]
    [string]$SelectedItemsJson = '[]',

    [Parameter(Mandatory = $false)]
    [switch]$DependenciesReviewed,

    [Parameter(Mandatory = $false)]
    [string]$ReviewedPlanJson,

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
        [string]$Token,

        [Parameter(Mandatory = $false)]
        [string]$LibraryId
    )

    if ([string]::IsNullOrWhiteSpace($LibraryId)) {
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
    }
    Assert-FabricGuid -Name 'Variable Library ID' -Value $LibraryId
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

function ConvertFrom-FabricItemSelection {
    <#
    .SYNOPSIS
        Validates explicit promotion scope without resolving or executing item content.
    .OUTPUTS
        PSCustomObject item name and type selections.
    #>
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet('Selected', 'All')]
        [string]$Scope,

        [Parameter(Mandatory = $false)]
        [string]$ItemsJson,

        [Parameter(Mandatory = $false)]
        [bool]$Reviewed = $false
    )

    $Entries = @()
    if (-not [string]::IsNullOrWhiteSpace($ItemsJson)) {
        $Parsed = ConvertFrom-Json -InputObject $ItemsJson -NoEnumerate -ErrorAction Stop
        if ($Parsed -isnot [array]) {
            throw 'SelectedItemsJson must be a JSON array of name/type objects'
        }
        $Entries = @($Parsed)
    }
    if ($Scope -eq 'All') {
        if ($Entries.Count -ne 0) {
            throw 'All scope cannot be combined with selected items'
        }
        return
    }
    if ($Entries.Count -lt 1 -or $Entries.Count -gt 300) {
        throw 'Selected scope requires between 1 and 300 items; it never falls back to All'
    }
    if (-not $Reviewed) {
        throw 'Selected scope requires DependenciesReviewed; review lineage and target dependencies first'
    }
    $Seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($Entry in $Entries) {
        $Properties = @($Entry.PSObject.Properties.Name)
        if (
            $Entry -isnot [pscustomobject] -or
            $Properties.Count -ne 2 -or
            'name' -cnotin $Properties -or 'type' -cnotin $Properties -or
            $Entry.name -isnot [string] -or $Entry.type -isnot [string] -or
            [string]::IsNullOrWhiteSpace($Entry.name) -or
            [string]::IsNullOrWhiteSpace($Entry.type)
        ) {
            throw 'Each selected item must contain only non-empty string name and type fields'
        }
        if (-not $Seen.Add("$($Entry.type)`0$($Entry.name)")) {
            throw "Duplicate selected item '$($Entry.name)' ($($Entry.type))"
        }
        [pscustomobject]@{ Name = $Entry.name; Type = $Entry.type }
    }
}

function Get-FabricDeploymentStageItems {
    <#
    .SYNOPSIS
        Lists every supported item in one deployment stage.
    .OUTPUTS
        PSCustomObject deployment stage items.
    #>
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory = $true)]
        [string]$PipelineId,

        [Parameter(Mandatory = $true)]
        [string]$StageId,

        [Parameter(Mandatory = $true)]
        [string]$Token
    )

    $NextUri = "$FabricApi/deploymentPipelines/$PipelineId/stages/$StageId/items"
    while (-not [string]::IsNullOrWhiteSpace($NextUri)) {
        $Page = Invoke-FabricRequest -Method Get -Uri $NextUri -Token $Token `
            -SkillName 'deployment-pipelines-authoring-cli'
        if ($null -eq $Page -or $null -eq $Page.value) {
            throw 'Fabric returned an invalid stage-items collection'
        }
        foreach ($Item in @($Page.value)) {
            Assert-FabricGuid -Name 'Stage item ID' -Value ([string]$Item.itemId)
            if (
                [string]::IsNullOrWhiteSpace([string]$Item.itemDisplayName) -or
                [string]::IsNullOrWhiteSpace([string]$Item.itemType)
            ) {
                throw 'Fabric returned an item without a name or type'
            }
            $Item
        }
        $NextUri = [string]$Page.continuationUri
    }
}

function New-FabricPromotionPlan {
    <#
    .SYNOPSIS
        Resolves an exact, read-only promotion plan from source-stage metadata.
    .OUTPUTS
        PSCustomObject promotion plan.
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

        [Parameter(Mandatory = $true)]
        [ValidateSet('Selected', 'All')]
        [string]$Scope,

        [Parameter(Mandatory = $false)]
        [string]$ItemsJson,

        [Parameter(Mandatory = $false)]
        [bool]$Reviewed = $false,

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
    $Requests = @(ConvertFrom-FabricItemSelection -Scope $Scope `
        -ItemsJson $ItemsJson -Reviewed $Reviewed)
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
    if (-not [string]::IsNullOrWhiteSpace($PlanId)) {
        if (-not $UsePreviewPlan) {
            throw 'EnablePreviewDeploymentPlan is required when DeploymentPlanId is set'
        }
        Assert-FabricGuid -Name 'DeploymentPlanId' -Value $PlanId
    }
    elseif ($UsePreviewPlan) {
        throw 'DeploymentPlanId is required when EnablePreviewDeploymentPlan is set'
    }
    $SourceItems = @(Get-FabricDeploymentStageItems -PipelineId $PipelineId `
        -StageId $Source.id -Token $Token)
    $TargetItems = @(Get-FabricDeploymentStageItems -PipelineId $PipelineId `
        -StageId $Target.id -Token $Token)
    $Selected = @()
    if ($Scope -eq 'All') {
        $Selected = @($SourceItems | Sort-Object itemId)
    }
    else {
        foreach ($Request in $Requests) {
            $Matches = @($SourceItems | Where-Object {
                $_.itemDisplayName -ceq $Request.Name -and $_.itemType -ceq $Request.Type
            })
            if ($Matches.Count -ne 1) {
                throw "Expected one source item '$($Request.Name)' ($($Request.Type)), found $($Matches.Count)"
            }
            $Selected += $Matches[0]
        }
    }
    if ($Selected.Count -lt 1 -or $Selected.Count -gt 300) {
        throw 'A promotion must resolve between 1 and 300 source items'
    }
    $TargetById = @{}
    foreach ($Item in $TargetItems) { $TargetById[$Item.itemId] = $Item }
    $PlannedItems = @(
        foreach ($Item in $Selected) {
            $TargetId = [string]$Item.targetItemId
            if (-not [string]::IsNullOrWhiteSpace($TargetId)) {
                if (
                    -not $TargetById.ContainsKey($TargetId) -or
                    $TargetById[$TargetId].itemType -cne $Item.itemType
                ) {
                    throw "Paired target for '$($Item.itemDisplayName)' is missing or has a different type"
                }
            }
            [pscustomobject][ordered]@{
                Name = [string]$Item.itemDisplayName
                Type = [string]$Item.itemType
                SourceItemId = [string]$Item.itemId
                TargetItemId = $TargetId
                Action = if ($TargetId) { 'Update' } else { 'Create' }
            }
        }
    )
    $Activation = $null
    if (
        -not [string]::IsNullOrWhiteSpace($LibraryName) -and
        @($PlannedItems | Where-Object {
            $_.Type -ceq 'VariableLibrary' -and $_.Name -ceq $LibraryName
        }).Count -gt 0
    ) {
        $Activation = [pscustomobject][ordered]@{
            LibraryName = $LibraryName
            ValueSetName = $ValueSetName
        }
    }
    return [pscustomobject][ordered]@{
        Version = 1
        Operation = 'PlanPromotion'
        Status = 'Planned'
        PipelineId = $PipelineId
        SourceStage = $SourceName
        TargetStage = $TargetName
        SourceStageId = [string]$Source.id
        TargetStageId = [string]$Target.id
        SourceWorkspaceId = [string]$Source.workspaceId
        TargetWorkspaceId = [string]$Target.workspaceId
        PromotionScope = if ($Scope -eq 'All') { 'All' } else { 'Selected' }
        DependenciesReviewed = $Reviewed
        DeploymentNote = $Note
        DeploymentPlanId = [string]$PlanId
        UsePreviewDeploymentPlan = $UsePreviewPlan.IsPresent
        VariableLibrary = $Activation
        Items = @($PlannedItems)
    }
}

function Invoke-FabricStagePromotion {
    <#
    .SYNOPSIS
        Deploys only planned source IDs and verifies selected and unselected target metadata.
    .OUTPUTS
        PSCustomObject verified promotion result.
    #>
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$PromotionPlan,

        [Parameter(Mandatory = $true)]
        [string]$Token
    )

    $Items = @($PromotionPlan.Items)
    if ($Items.Count -lt 1 -or $Items.Count -gt 300) {
        throw 'Promotion plan must contain between 1 and 300 items'
    }
    $Before = @(Get-FabricDeploymentStageItems -PipelineId $PromotionPlan.PipelineId `
        -StageId $PromotionPlan.TargetStageId -Token $Token)
    $SelectedTargetIds = @($Items.TargetItemId | Where-Object { $_ })
    $Unselected = @{}
    foreach ($Item in $Before | Where-Object { $_.itemId -notin $SelectedTargetIds }) {
        $Unselected[$Item.itemId] = $Item |
            Select-Object itemId, itemDisplayName, itemType, sourceItemId, lastDeploymentTime |
            ConvertTo-Json -Compress
    }
    $BodyObject = @{
        sourceStageId = $PromotionPlan.SourceStageId
        targetStageId = $PromotionPlan.TargetStageId
        note = $PromotionPlan.DeploymentNote
        items = @($Items | ForEach-Object {
            @{ sourceItemId = $_.SourceItemId; itemType = $_.Type }
        })
    }
    $DeployUri = "$FabricApi/deploymentPipelines/$($PromotionPlan.PipelineId)/deploy"
    if ($PromotionPlan.UsePreviewDeploymentPlan) {
        $BodyObject.options = @{
            deploymentPlan = @{
                referenceType = 'ByItemId'
                itemId = $PromotionPlan.DeploymentPlanId
            }
        }
        $DeployUri += '?beta=true'
    }
    $null = Invoke-FabricRequest -Method Post -Uri $DeployUri -Token $Token `
        -SkillName 'deployment-pipelines-authoring-cli' `
        -Body ($BodyObject | ConvertTo-Json -Depth 10 -Compress)

    $VerifiedTargets = @{}
    for ($Attempt = 0; $Attempt -lt 3; $Attempt++) {
        $AfterSource = @(Get-FabricDeploymentStageItems -PipelineId $PromotionPlan.PipelineId `
            -StageId $PromotionPlan.SourceStageId -Token $Token)
        $AfterTarget = @(Get-FabricDeploymentStageItems -PipelineId $PromotionPlan.PipelineId `
            -StageId $PromotionPlan.TargetStageId -Token $Token)
        $AfterById = @{}
        foreach ($Item in $AfterTarget) { $AfterById[$Item.itemId] = $Item }
        $Missing = @(
            foreach ($Item in $Items) {
                $Source = @($AfterSource | Where-Object itemId -eq $Item.SourceItemId)
                $TargetId = if ($Source.Count -eq 1) { [string]$Source[0].targetItemId } else { '' }
                if (
                    -not $TargetId -or -not $AfterById.ContainsKey($TargetId) -or
                    $AfterById[$TargetId].itemType -cne $Item.Type -or
                    ($Item.TargetItemId -and $Item.TargetItemId -ne $TargetId)
                ) {
                    $Item.Name
                }
                else {
                    $VerifiedTargets[$Item.SourceItemId] = $AfterById[$TargetId]
                }
            }
        )
        if ($Missing.Count -eq 0) { break }
        if ($Attempt -eq 2) {
            throw "Deployment completed but selected item pairing could not be verified: $($Missing -join ', ')"
        }
        Start-Sleep -Seconds 2
    }
    foreach ($Id in $Unselected.Keys) {
        $Current = if ($AfterById.ContainsKey($Id)) {
            $AfterById[$Id] |
                Select-Object itemId, itemDisplayName, itemType, sourceItemId, lastDeploymentTime |
                ConvertTo-Json -Compress
        } else { '' }
        if ($Current -cne $Unselected[$Id]) {
            throw "Unselected target item metadata changed during promotion: $Id"
        }
    }
    $VariableResult = $null
    if ($null -ne $PromotionPlan.VariableLibrary) {
        $Library = @($Items | Where-Object {
            $_.Type -ceq 'VariableLibrary' -and
            $_.Name -ceq $PromotionPlan.VariableLibrary.LibraryName
        })[0]
        $TargetLibrary = $VerifiedTargets[$Library.SourceItemId]
        $VariableResult = Set-FabricVariableLibraryValueSet `
            -Workspace $PromotionPlan.TargetWorkspaceId `
            -LibraryName $TargetLibrary.itemDisplayName -LibraryId $TargetLibrary.itemId `
            -ValueSetName $PromotionPlan.VariableLibrary.ValueSetName -Token $Token
    }
    return [pscustomobject]@{
        Operation       = 'Promote'
        Status          = 'Succeeded'
        SourceStage     = $PromotionPlan.SourceStage
        TargetStage     = $PromotionPlan.TargetStage
        PromotionScope  = $PromotionPlan.PromotionScope
        DependenciesReviewed = $PromotionPlan.DependenciesReviewed
        Items           = $Items
        VerifiedItemCount = $VerifiedTargets.Count
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
    if ($Result.PromotionScope) {
        $Rows += "* Scope: ``$($Result.PromotionScope)``"
        $Rows += "* Dependency review confirmed: ``$($Result.DependenciesReviewed)``"
        $Details = [ordered]@{
            'Pipeline ID' = $Result.PipelineId
            'Source workspace' = $Result.SourceWorkspaceId
            'Target workspace' = $Result.TargetWorkspaceId
            'Deployment note' = $Result.DeploymentNote
            'Preview Deployment Plan' = if ($Result.UsePreviewDeploymentPlan) {
                $Result.DeploymentPlanId
            } else { 'Disabled' }
        }
        foreach ($Label in $Details.Keys) {
            if ($null -ne $Details[$Label]) {
                $Encoded = [Net.WebUtility]::HtmlEncode([string]$Details[$Label]).
                    Replace("`r", ' ').Replace("`n", ' ')
                $Rows += "* ${Label}: <code>$Encoded</code>"
            }
        }
        $Rows += '* Dependency discovery is not available from stage metadata; review Fabric lineage manually.'
        $Rows += '* Only the listed source IDs are submitted. Unselected items are not added automatically.'
        $Rows += ''
        $Rows += '| Item | Type | Action | Source item ID | Paired target ID |'
        $Rows += '| --- | --- | --- | --- | --- |'
        foreach ($Item in @($Result.Items)) {
            $Cells = @(
                foreach ($Value in @(
                    $Item.Name, $Item.Type, $Item.Action, $Item.SourceItemId, $Item.TargetItemId
                )) {
                    $Encoded = [Net.WebUtility]::HtmlEncode([string]$Value).
                        Replace('|', '&#124;').Replace("`r", ' ').Replace("`n", ' ')
                    "<code>$Encoded</code>"
                }
            )
            $Rows += '| ' + ($Cells -join ' | ') + ' |'
        }
        $Rows += ''
        if ($Result.VariableLibrary) {
            $Rows += '* Variable Library activation is restricted to the selected library.'
            $Library = [Net.WebUtility]::HtmlEncode([string]$Result.VariableLibrary.LibraryName)
            $ValueSet = [Net.WebUtility]::HtmlEncode([string]$Result.VariableLibrary.ValueSetName)
            $Rows += "* Activate <code>$Library</code> value set <code>$ValueSet</code>."
        }
        else {
            $Rows += '* No Variable Library activation is requested for this selection.'
        }
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
            $null = @(ConvertFrom-FabricItemSelection -Scope $PromotionScope `
                -ItemsJson $SelectedItemsJson -Reviewed $DependenciesReviewed.IsPresent)
            if ($DryRun) {
                if ($Operation -eq 'PlanPromotion') {
                    throw 'PlanPromotion reads Fabric metadata; use Promote -DryRun for offline validation'
                }
                $Result = [pscustomobject]@{
                    Operation   = $Operation
                    Status      = 'WouldPromote'
                    SourceStage = $SourceStageName
                    TargetStage = $TargetStageName
                    PromotionScope = $PromotionScope
                    DependenciesReviewed = $DependenciesReviewed.IsPresent
                    Items = @()
                }
            }
            else {
                if (
                    $Operation -eq 'Promote' -and
                    [string]::IsNullOrWhiteSpace($ReviewedPlanJson)
                ) {
                    throw 'Promote requires ReviewedPlanJson from a successful PlanPromotion operation'
                }
                $AccessToken = Get-FabricAccessToken
                $Plan = New-FabricPromotionPlan `
                    -PipelineId $DeploymentPipelineId `
                    -SourceName $SourceStageName -TargetName $TargetStageName `
                    -Note $DeploymentNote -Token $AccessToken `
                    -Scope $PromotionScope -ItemsJson $SelectedItemsJson `
                    -Reviewed $DependenciesReviewed.IsPresent `
                    -PlanId $DeploymentPlanId `
                    -UsePreviewPlan:$EnablePreviewDeploymentPlan `
                    -LibraryName $VariableLibraryName `
                    -ValueSetName $ActiveValueSetName
                if ($Operation -eq 'PlanPromotion') {
                    $Result = $Plan
                }
                else {
                    $ReviewedPlan = ConvertFrom-Json -InputObject $ReviewedPlanJson `
                        -ErrorAction Stop
                    $Expected = $Plan | ConvertTo-Json -Depth 20 -Compress
                    $Reviewed = $ReviewedPlan | ConvertTo-Json -Depth 20 -Compress
                    if ($Reviewed -cne $Expected) {
                        throw 'Promotion plan changed or does not match the reviewed scope; generate and review a new plan'
                    }
                    $Result = Invoke-FabricStagePromotion -PromotionPlan $Plan -Token $AccessToken
                }
            }
        }

        Write-FabricAlmSummary -Result $Result
        $Result | ConvertTo-Json -Depth 20
    }
    catch {
        Write-Error -ErrorAction Continue "Fabric ALM operation failed: $($_.Exception.Message)"
        exit 1
    }
}

#endregion Main Execution
