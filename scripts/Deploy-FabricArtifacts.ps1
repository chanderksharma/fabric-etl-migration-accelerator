#!/usr/bin/env pwsh
# Copyright (c) Microsoft Corporation.
# Microsoft Confidential - Internal InnerSource Use Only.
#Requires -Version 7.0

<#
.SYNOPSIS
    Deploys generated Microsoft Fabric definitions.
.DESCRIPTION
    Selects target-prefixed create-item envelopes from generated-fabric-workflows,
    authenticates with a Microsoft Entra service principal, creates or updates
    Fabric items, and verifies the persisted definition parts.
.PARAMETER WorkspaceId
    Target Fabric workspace ID. Defaults to FABRIC_WORKSPACE_ID.
.PARAMETER ArtifactRoot
    Root containing generated workflow directories.
.PARAMETER Target
    Artifact type to deploy: Both, Bundle, Dataflow, Notebook, or DataPipeline.
.PARAMETER WorkflowFilter
    PowerShell wildcard matched against workflow-relative directory paths.
.PARAMETER ConflictBehavior
    Behavior when an item with the same type and display name exists.
.PARAMETER DryRun
    Validates and lists local envelopes without authenticating or mutating Fabric.
.EXAMPLE
    ./scripts/Deploy-FabricArtifacts.ps1 -Target Dataflow `
        -WorkflowFilter 'alteryx-workflows/02_low_west_sample'
.NOTES
    Supports Microsoft Entra Workload Identity Federation (OIDC via GitHub Actions,
    AZURE_FEDERATED_TOKEN_FILE, or AZURE_FEDERATED_TOKEN) with AZURE_CLIENT_ID and
    AZURE_TENANT_ID, or AZURE_CLIENT_SECRET as an optional fallback.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$WorkspaceId = $env:FABRIC_WORKSPACE_ID,

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$ArtifactRoot = (Join-Path $PSScriptRoot '../generated-fabric-workflows'),

    [Parameter(Mandatory = $false)]
    [ValidateSet('Both', 'Bundle', 'Dataflow', 'Notebook', 'DataPipeline')]
    [string]$Target = 'Both',

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$WorkflowFilter = '*',

    [Parameter(Mandatory = $false)]
    [ValidateSet('Fail', 'Skip', 'Update')]
    [string]$ConflictBehavior = 'Update',

    [Parameter(Mandatory = $false)]
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$FabricApi = 'https://api.fabric.microsoft.com/v1'

Import-Module (Join-Path $PSScriptRoot 'FabricApi.psm1') -Force

#region Functions

function Get-DeploymentCandidates {
    <#
    .SYNOPSIS
        Loads and validates generated Fabric request envelopes.
    .OUTPUTS
        PSCustomObject deployment candidates.
    #>
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Root,

        [Parameter(Mandatory = $true)]
        [ValidateSet('Both', 'Bundle', 'Dataflow', 'Notebook', 'DataPipeline')]
        [string]$SelectedTarget,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Filter
    )

    $ResolvedRoot = (Resolve-Path -LiteralPath $Root).Path
    $RepositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
    $RepositoryPrefix = $RepositoryRoot + [IO.Path]::DirectorySeparatorChar
    if (
        $ResolvedRoot -ne $RepositoryRoot -and
        -not $ResolvedRoot.StartsWith($RepositoryPrefix, [StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "ArtifactRoot must be inside the repository: $ResolvedRoot"
    }
    $Files = Get-ChildItem -LiteralPath $ResolvedRoot -Recurse -File |
        Where-Object {
            $_.Name -in @(
                'dataflow-create-item.json',
                'notebook-create-item.json',
                'pipeline-create-item.json'
            )
        }
    $Candidates = foreach ($File in $Files) {
        if ($File.Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)) {
            throw "Artifact envelope cannot be a symbolic link or reparse point: $($File.FullName)"
        }
        if ($File.Length -gt 10MB) {
            throw "Artifact envelope exceeds the 10 MB limit: $($File.FullName)"
        }
        $ItemTarget = if ($File.Name.StartsWith('dataflow-', [StringComparison]::OrdinalIgnoreCase)) {
            'Dataflow'
        }
        elseif ($File.Name.StartsWith('pipeline-', [StringComparison]::OrdinalIgnoreCase)) {
            'DataPipeline'
        }
        else {
            'Notebook'
        }
        if (
            $SelectedTarget -notin @('Both', 'Bundle') -and
            $SelectedTarget -ne $ItemTarget
        ) {
            continue
        }

        $RelativeDirectory = [IO.Path]::GetRelativePath(
            $ResolvedRoot,
            $File.Directory.FullName
        ).Replace('\', '/')
        if ($RelativeDirectory -notlike $Filter) {
            continue
        }
        if (
            $SelectedTarget -eq 'Bundle' -and
            -not (Test-Path -LiteralPath (
                Join-Path $File.Directory.FullName 'deployment-bundle.json'
            ))
        ) {
            continue
        }

        $Payload = Get-Content -LiteralPath $File.FullName -Raw | ConvertFrom-Json
        if ($Payload.type -ne $ItemTarget) {
            throw "$($File.FullName) declares type '$($Payload.type)', expected '$ItemTarget'"
        }
        if ([string]::IsNullOrWhiteSpace($Payload.displayName)) {
            throw "$($File.FullName) has no displayName"
        }
        if (-not $Payload.definition.parts) {
            throw "$($File.FullName) has no definition parts"
        }

        $ExpectedParts = if ($ItemTarget -eq 'Dataflow') {
            @('mashup.pq', 'queryMetadata.json', '.platform')
        }
        elseif ($ItemTarget -eq 'DataPipeline') {
            @('pipeline-content.json', '.platform')
        }
        else {
            @('notebook-content.ipynb', '.platform')
        }
        $ActualParts = @($Payload.definition.parts.path)
        $MissingParts = @($ExpectedParts | Where-Object { $_ -notin $ActualParts })
        if ($MissingParts.Count -gt 0) {
            throw "$($File.FullName) is missing: $($MissingParts -join ', ')"
        }

        $RuntimeReady = $true
        $ValidationQueryNames = @()
        $RequiredBindings = @()
        if ($ItemTarget -eq 'Dataflow') {
            $Manifest = $null
            $ManifestPath = Join-Path $File.Directory.FullName 'dataflow-manifest.json'
            if (Test-Path -LiteralPath $ManifestPath) {
                $Manifest = Get-Content -LiteralPath $ManifestPath -Raw |
                    ConvertFrom-Json
                $RuntimeReady = [bool]$Manifest.runtime_ready
                $RequiredBindings = @($Manifest.required_bindings)
            }

            $MetadataPart = $Payload.definition.parts |
                Where-Object path -eq 'queryMetadata.json' |
                Select-Object -First 1
            $MetadataText = [Text.Encoding]::UTF8.GetString(
                [Convert]::FromBase64String([string]$MetadataPart.payload)
            )
            $Metadata = $MetadataText | ConvertFrom-Json
            $QueryProperties = @($Metadata.queriesMetadata.PSObject.Properties)
            $ValidationQueryNames = @(
                $QueryProperties |
                    Where-Object {
                        $_.Value.loadEnabled -ne $false -and
                        $_.Value.isHidden -ne $true
                    } |
                    ForEach-Object Name
            )
            if ($ValidationQueryNames.Count -eq 0 -and $Manifest -and $Manifest.loaded_queries) {
                $VisibleQueryNames = @(
                    $QueryProperties |
                        Where-Object { $_.Value.isHidden -ne $true } |
                        ForEach-Object Name
                )
                $ValidationQueryNames = @(
                    @($Manifest.loaded_queries) |
                        Where-Object { $_ -in $VisibleQueryNames }
                )
            }
            if ($ValidationQueryNames.Count -eq 0) {
                $ValidationQueryNames = @(
                    $QueryProperties |
                        Where-Object {
                            $_.Value.isHidden -ne $true -and
                            $_.Name -ne 'SourceBindings'
                        } |
                        ForEach-Object Name |
                        Select-Object -Last 1
                )
            }
            if ($ValidationQueryNames.Count -eq 0) {
                throw "$($File.FullName) has no Dataflow query to validate"
            }
        }

        [pscustomobject]@{
            Target            = $ItemTarget
            DisplayName       = [string]$Payload.displayName
            RelativeDirectory = $RelativeDirectory
            RequestPath       = $File.FullName
            Payload           = $Payload
            ExpectedParts     = $ExpectedParts
            RuntimeReady      = $RuntimeReady
            ValidationQueryNames = $ValidationQueryNames
            RequiredBindings  = $RequiredBindings
        }
    }

    $Duplicates = $Candidates |
        Group-Object -Property Target, DisplayName |
        Where-Object Count -gt 1
    if ($Duplicates) {
        throw "Duplicate target/displayName envelopes: $($Duplicates.Name -join '; ')"
    }
    $Order = @{ Dataflow = 0; Notebook = 1; DataPipeline = 2 }
    return $Candidates | Sort-Object `
        @{ Expression = { $Order[$_.Target] } }, RelativeDirectory
}

function Get-FabricItems {
    <#
    .SYNOPSIS
        Lists all Fabric items of one supported target type.
    .OUTPUTS
        PSCustomObject Fabric items.
    #>
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Workspace,

        [Parameter(Mandatory = $true)]
        [ValidateSet('Dataflow', 'Notebook', 'DataPipeline')]
        [string]$ItemTarget,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Token
    )

    $Collection = if ($ItemTarget -eq 'Dataflow') {
        'dataflows'
    }
    elseif ($ItemTarget -eq 'DataPipeline') {
        'dataPipelines'
    }
    else {
        'notebooks'
    }
    $SkillName = if ($ItemTarget -eq 'Notebook') { 'spark-cli' } else { 'dataflows-cli' }
    $NextUri = "$FabricApi/workspaces/$Workspace/$Collection"
    while ($NextUri) {
        $Page = Invoke-FabricRequest -Method Get -Uri $NextUri -Token $Token `
            -SkillName $SkillName
        foreach ($Item in @($Page.value)) {
            $Item
        }
        $NextUri = [string]$Page.continuationUri
    }
}

function Confirm-FabricDefinition {
    <#
    .SYNOPSIS
        Reads a persisted definition and validates its part paths.
    .OUTPUTS
        System.String definition part paths.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Workspace,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$ItemId,

        [Parameter(Mandatory = $true)]
        [ValidateSet('Dataflow', 'Notebook', 'DataPipeline')]
        [string]$ItemTarget,

        [Parameter(Mandatory = $true)]
        [string[]]$ExpectedParts,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Token
    )

    if ($ItemTarget -eq 'Dataflow') {
        $Uri = "$FabricApi/workspaces/$Workspace/dataflows/$ItemId/getDefinition"
        $SkillName = 'dataflows-cli'
        $Definition = Invoke-FabricRequest -Method Post -Uri $Uri -Token $Token `
            -SkillName $SkillName -FetchResult
    }
    elseif ($ItemTarget -eq 'DataPipeline') {
        $Uri = "$FabricApi/workspaces/$Workspace/dataPipelines/$ItemId/getDefinition"
        $SkillName = 'dataflows-cli'
        $Definition = Invoke-FabricRequest -Method Post -Uri $Uri -Token $Token `
            -SkillName $SkillName -FetchResult
    }
    else {
        $Uri = "$FabricApi/workspaces/$Workspace/notebooks/$ItemId/getDefinition?format=ipynb"
        $SkillName = 'spark-cli'
        $Definition = Invoke-FabricRequest -Method Post -Uri $Uri -Token $Token `
            -SkillName $SkillName -Body '{}' -FetchResult
    }

    $PartPaths = @($Definition.definition.parts.path)
    $MissingParts = @($ExpectedParts | Where-Object { $_ -notin $PartPaths })
    if ($MissingParts.Count -gt 0) {
        throw "Item $ItemId readback is missing: $($MissingParts -join ', ')"
    }
    return $PartPaths
}

function Test-FabricDataflowQuery {
    <#
    .SYNOPSIS
        Validates a saved Dataflow query through executeQuery.
    .OUTPUTS
        System.String validation status.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Workspace,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$ItemId,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$QueryName,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Token
    )

    $OutputPath = Join-Path ([IO.Path]::GetTempPath()) (
        "fabric-query-$([guid]::NewGuid().ToString('N')).arrow"
    )
    try {
        $Body = @{ QueryName = $QueryName } | ConvertTo-Json -Compress
        $Response = Invoke-WebRequest -Method Post `
            -Uri "$FabricApi/workspaces/$Workspace/dataflows/$ItemId/executeQuery" `
            -Headers @{
                Authorization       = "Bearer $Token"
                'x-ms-fabric-skill' = 'dataflows-cli'
                'Content-Type'      = 'application/json'
            } `
            -Body $Body -OutFile $OutputPath -SkipHttpErrorCheck
        if ($Response.StatusCode -lt 200 -or $Response.StatusCode -ge 300) {
            $ErrorText = if (Test-Path -LiteralPath $OutputPath) {
                [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($OutputPath))
            }
            else {
                [string]$Response.Content
            }
            throw "executeQuery failed ($($Response.StatusCode)) for '$QueryName': $ErrorText"
        }
        $Bytes = [IO.File]::ReadAllBytes($OutputPath)
        if ($Bytes.Length -lt 4) {
            throw 'executeQuery returned an empty or truncated response'
        }
        $Text = [Text.Encoding]::UTF8.GetString($Bytes)
        if ($Text.Contains('"Error"')) {
            throw 'executeQuery returned an embedded Power Query error'
        }
        if ([Convert]::ToHexString($Bytes[0..3]) -ne 'FFFFFFFF') {
            throw 'executeQuery did not return an Apache Arrow stream'
        }
        return 'SPNQueryValidated'
    }
    finally {
        Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-FabricDeployment {
    <#
    .SYNOPSIS
        Creates or updates selected Fabric artifacts.
    .OUTPUTS
        PSCustomObject deployment results.
    #>
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Workspace,

        [Parameter(Mandatory = $true)]
        [pscustomobject[]]$Candidates,

        [Parameter(Mandatory = $true)]
        [ValidateSet('Fail', 'Skip', 'Update')]
        [string]$OnConflict,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Token
    )

    $ExistingByTarget = @{}
    $DeployedByDirectory = @{}
    foreach ($ItemTarget in @($Candidates.Target | Sort-Object -Unique)) {
        $ExistingByTarget[$ItemTarget] = @(Get-FabricItems -Workspace $Workspace `
            -ItemTarget $ItemTarget -Token $Token)
    }

    foreach ($Candidate in $Candidates) {
        $Matches = @(
            $ExistingByTarget[$Candidate.Target] |
                Where-Object displayName -eq $Candidate.DisplayName
        )
        if ($Matches.Count -gt 1) {
            throw "Multiple $($Candidate.Target) items named '$($Candidate.DisplayName)' exist"
        }

        $SkillName = if ($Candidate.Target -eq 'Notebook') {
            'spark-cli'
        }
        else {
            'dataflows-cli'
        }
        $DeploymentPayload = $Candidate.Payload |
            ConvertTo-Json -Depth 100 -Compress |
            ConvertFrom-Json
        if ($Candidate.Target -eq 'DataPipeline') {
            $Dependencies = $DeployedByDirectory[$Candidate.RelativeDirectory]
            $ContentPart = $DeploymentPayload.definition.parts |
                Where-Object path -eq 'pipeline-content.json' |
                Select-Object -First 1
            $Content = [Text.Encoding]::UTF8.GetString(
                [Convert]::FromBase64String([string]$ContentPart.payload)
            )
            $NeedsDataflow = $Content.Contains('{{DATAFLOW_ITEM_ID}}')
            $NeedsNotebook = $Content.Contains('{{NOTEBOOK_ITEM_ID}}')
            if (
                ($NeedsDataflow -and (-not $Dependencies -or -not $Dependencies.Dataflow)) -or
                ($NeedsNotebook -and (-not $Dependencies -or -not $Dependencies.Notebook))
            ) {
                throw "Pipeline dependencies were not deployed for '$($Candidate.RelativeDirectory)'"
            }
            $Content = $Content.Replace('{{WORKSPACE_ID}}', $Workspace)
            if ($NeedsDataflow) {
                $Content = $Content.Replace(
                    '{{DATAFLOW_ITEM_ID}}',
                    [string]$Dependencies.Dataflow
                )
            }
            if ($NeedsNotebook) {
                $Content = $Content.Replace(
                    '{{NOTEBOOK_ITEM_ID}}',
                    [string]$Dependencies.Notebook
                )
            }
            $ContentPart.payload = [Convert]::ToBase64String(
                [Text.Encoding]::UTF8.GetBytes($Content)
            )
        }
        $Action = 'Created'
        if ($Matches.Count -eq 1) {
            if ($OnConflict -eq 'Fail') {
                throw "$($Candidate.Target) '$($Candidate.DisplayName)' already exists"
            }
            if ($OnConflict -eq 'Skip') {
                if (-not $DeployedByDirectory.ContainsKey($Candidate.RelativeDirectory)) {
                    $DeployedByDirectory[$Candidate.RelativeDirectory] = @{}
                }
                $DeployedByDirectory[$Candidate.RelativeDirectory][$Candidate.Target] = (
                    [string]$Matches[0].id
                )
                [pscustomobject]@{
                    Target      = $Candidate.Target
                    DisplayName = $Candidate.DisplayName
                    ItemId      = [string]$Matches[0].id
                    Action      = 'Skipped'
                    Parts       = @()
                    RefreshStatus = 'NotRequested'
                }
                continue
            }

            $ItemId = [string]$Matches[0].id
            $UpdateBody = @{ definition = $DeploymentPayload.definition } |
                ConvertTo-Json -Depth 100 -Compress
            $UpdateUri = if ($Candidate.Target -eq 'Dataflow') {
                "$FabricApi/workspaces/$Workspace/dataflows/$ItemId/updateDefinition?updateMetadata=true"
            }
            elseif ($Candidate.Target -eq 'DataPipeline') {
                "$FabricApi/workspaces/$Workspace/dataPipelines/$ItemId/updateDefinition"
            }
            else {
                "$FabricApi/workspaces/$Workspace/notebooks/$ItemId/updateDefinition"
            }
            $null = Invoke-FabricRequest -Method Post -Uri $UpdateUri -Token $Token `
                -SkillName $SkillName -Body $UpdateBody
            $Action = 'Updated'
        }
        else {
            $CreateBody = $DeploymentPayload | ConvertTo-Json -Depth 100 -Compress
            $null = Invoke-FabricRequest -Method Post `
                -Uri "$FabricApi/workspaces/$Workspace/items" -Token $Token `
                -SkillName $SkillName -Body $CreateBody
            $CreatedMatches = @(
                Get-FabricItems -Workspace $Workspace -ItemTarget $Candidate.Target `
                    -Token $Token |
                    Where-Object displayName -eq $Candidate.DisplayName
            )
            if ($CreatedMatches.Count -ne 1) {
                throw "Expected one created item named '$($Candidate.DisplayName)', found $($CreatedMatches.Count)"
            }
            $ItemId = [string]$CreatedMatches[0].id
            $ExistingByTarget[$Candidate.Target] += $CreatedMatches[0]
        }
        if (-not $DeployedByDirectory.ContainsKey($Candidate.RelativeDirectory)) {
            $DeployedByDirectory[$Candidate.RelativeDirectory] = @{}
        }
        $DeployedByDirectory[$Candidate.RelativeDirectory][$Candidate.Target] = $ItemId

        $Parts = @(Confirm-FabricDefinition -Workspace $Workspace -ItemId $ItemId `
            -ItemTarget $Candidate.Target -ExpectedParts $Candidate.ExpectedParts `
            -Token $Token)
        $RefreshStatus = 'NotApplicable'
        if ($Candidate.Target -eq 'Dataflow') {
            if (-not $Candidate.RuntimeReady) {
                $RefreshStatus = 'BindingsRequired'
                Write-Warning (
                    "Dataflow definition deployed without runtime validation. " +
                    "Resolve required bindings first: " +
                    "$($Candidate.RequiredBindings -join ', ')"
                )
            }
            else {
                foreach ($QueryName in $Candidate.ValidationQueryNames) {
                    $null = Test-FabricDataflowQuery -Workspace $Workspace `
                        -ItemId $ItemId -QueryName $QueryName -Token $Token
                }
                $RefreshStatus = 'SPNQueriesValidated'
                Write-Warning (
                    "Fabric blocks SPN-triggered Dataflow refresh. " +
                    "Saved queries were validated with executeQuery; refresh requires " +
                    "an authorized user or another supported orchestration identity."
                )
            }
        }
        [pscustomobject]@{
            Target      = $Candidate.Target
            DisplayName = $Candidate.DisplayName
            ItemId      = $ItemId
            Action      = $Action
            Parts       = $Parts
            RefreshStatus = $RefreshStatus
        }
    }
}

function Write-DeploymentSummary {
    <#
    .SYNOPSIS
        Writes deployment results to the GitHub step summary.
    .OUTPUTS
        None.
    #>
    [CmdletBinding()]
    [OutputType([void])]
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject[]]$Results,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Workspace,

        [Parameter(Mandatory = $true)]
        [bool]$IsDryRun
    )

    if ([string]::IsNullOrWhiteSpace($env:GITHUB_STEP_SUMMARY)) {
        return
    }
    $Rows = @(
        '# Fabric artifact deployment'
        ''
        "* Workspace: ``$Workspace``"
        "* Dry run: ``$IsDryRun``"
        ''
        '| Target | Display name | Action | Item ID | Runtime validation |'
        '|--------|--------------|--------|---------|--------------------|'
        foreach ($Result in $Results) {
            "| $($Result.Target) | $($Result.DisplayName) | $($Result.Action) | $($Result.ItemId) | $($Result.RefreshStatus) |"
        }
        ''
    )
    Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Value $Rows -Encoding utf8
}

#endregion Functions

#region Main Execution

if ($MyInvocation.InvocationName -ne '.') {
    try {
        $Candidates = @(
            Get-DeploymentCandidates -Root $ArtifactRoot -SelectedTarget $Target `
                -Filter $WorkflowFilter
        )
        if ($Candidates.Count -eq 0) {
            throw "No deployable envelopes matched target '$Target' and filter '$WorkflowFilter'"
        }

        if ($DryRun) {
            $Results = @(
                foreach ($Candidate in $Candidates) {
                    [pscustomobject]@{
                        Target      = $Candidate.Target
                        DisplayName = $Candidate.DisplayName
                        ItemId      = ''
                        Action      = 'WouldDeploy'
                        Parts       = $Candidate.ExpectedParts
                        RefreshStatus = if (
                            $Candidate.Target -eq 'Dataflow' -and
                            -not $Candidate.RuntimeReady
                        ) {
                            'BindingsRequired'
                        }
                        elseif ($Candidate.Target -eq 'Dataflow') {
                            'WouldValidateQueries'
                        }
                        else {
                            'NotApplicable'
                        }
                    }
                }
            )
        }
        else {
            if ([string]::IsNullOrWhiteSpace($WorkspaceId)) {
                throw 'WorkspaceId or FABRIC_WORKSPACE_ID is required'
            }
            $AccessToken = Get-FabricAccessToken
            $Results = @(
                Invoke-FabricDeployment -Workspace $WorkspaceId -Candidates $Candidates `
                    -OnConflict $ConflictBehavior -Token $AccessToken
            )
        }

        Write-DeploymentSummary -Results $Results -Workspace $WorkspaceId `
            -IsDryRun $DryRun.IsPresent
        $Results | ConvertTo-Json -Depth 10
    }
    catch {
        Write-Error -ErrorAction Continue "Fabric artifact deployment failed: $($_.Exception.Message)"
        exit 1
    }
}

#endregion Main Execution
