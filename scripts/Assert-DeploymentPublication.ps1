#!/usr/bin/env pwsh
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
#Requires -Version 7.0

<#
.SYNOPSIS
    Verify the exact publication manifest and files before deployment.
.DESCRIPTION
    Checks a content-addressed repository directory against a locally verified
    manifest hash. The caller must separately verify the CI event and checkout.
.PARAMETER ArtifactRoot
    Repository-relative publication directory.
.PARAMETER ExpectedManifestSha256
    SHA-256 hash of the exact approved publication manifest bytes.
.EXAMPLE
    ./scripts/Assert-DeploymentPublication.ps1 -ArtifactRoot $root -ExpectedManifestSha256 $hash
.NOTES
    Requires a trusted CI definition, checkout, and runner.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ArtifactRoot,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string]$ExpectedManifestSha256
)

$ErrorActionPreference = 'Stop'

#region Main Execution
if ($MyInvocation.InvocationName -ne '.') {
    try {
        if ($ArtifactRoot -cnotmatch '^published-fabric-workflows/([0-9a-f]{32})/([0-9a-f]{64})$') {
            throw 'Invalid publication repository path'
        }
        $RunId = $Matches[1]
        $Root = (Get-Location).ProviderPath
        foreach ($Segment in $ArtifactRoot.Split('/')) {
            $Root = Join-Path $Root $Segment
            $Item = Get-Item -LiteralPath $Root -Force
            if (-not $Item.PSIsContainer -or
                ($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
                throw 'Publication directory is missing or linked'
            }
        }
        $ManifestPath = Join-Path $Root 'publication-manifest.json'
        $ManifestItem = Get-Item -LiteralPath $ManifestPath -Force
        if ($ManifestItem.PSIsContainer -or
            ($ManifestItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
            throw 'Publication manifest is not a regular file'
        }
        $ManifestBytes = [System.IO.File]::ReadAllBytes($ManifestPath)
        $Hasher = [System.Security.Cryptography.SHA256]::Create()
        try {
            $ManifestHash = [System.BitConverter]::ToString(
                $Hasher.ComputeHash($ManifestBytes)
            ).Replace('-', '').ToLowerInvariant()
        }
        finally {
            $Hasher.Dispose()
        }
        if ($ManifestHash -cne $ExpectedManifestSha256) {
            throw 'Publication manifest hash does not match the dispatch'
        }
        $Manifest = [System.Text.Encoding]::UTF8.GetString($ManifestBytes) |
            ConvertFrom-Json -AsHashtable
        if ($Manifest.version -ne 1 -or $Manifest.run_id -cne $RunId -or
            $Manifest.files -isnot [array] -or $Manifest.files.Count -eq 0) {
            throw 'Publication manifest is invalid'
        }
        $ExpectedPaths = [System.Collections.Generic.HashSet[string]]::new(
            [System.StringComparer]::OrdinalIgnoreCase
        )
        foreach ($Entry in $Manifest.files) {
            $RelativePath = $Entry.path
            if ($RelativePath -isnot [string] -or
                $RelativePath -notmatch '^[^\\/:]+(?:/[^\\/:]+)*$' -or
                $RelativePath -match '[\x00-\x1f]' -or
                @($RelativePath.Split('/') | Where-Object { $_ -in @('.', '..') -or $_ -match '[. ]$' }).Count -gt 0 -or
                $RelativePath -ieq 'publication-manifest.json' -or
                -not $ExpectedPaths.Add($RelativePath)) {
                throw 'Publication contains an invalid or duplicate path'
            }
            if ($Entry.sha256 -isnot [string] -or $Entry.sha256 -cnotmatch '^[0-9a-f]{64}$' -or
                ($Entry.size_bytes -isnot [int] -and $Entry.size_bytes -isnot [long]) -or
                $Entry.size_bytes -lt 0) {
                throw 'Publication contains invalid file metadata'
            }
            $File = Get-Item -LiteralPath (Join-Path $Root $RelativePath) -Force
            if ($File.PSIsContainer -or
                ($File.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
                $File.Length -ne $Entry.size_bytes) {
                throw "Publication file is missing, linked, or has changed: $RelativePath"
            }
            if ((Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -cne
                $Entry.sha256) {
                throw "Publication file hash has changed: $RelativePath"
            }
        }
        foreach ($Item in Get-ChildItem -LiteralPath $Root -Recurse -Force) {
            if ($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                throw 'Publication contains a linked path'
            }
            if ($Item.PSIsContainer) {
                continue
            }
            $RelativePath = [System.IO.Path]::GetRelativePath($Root, $Item.FullName).Replace('\', '/')
            if ($RelativePath -cne 'publication-manifest.json' -and
                -not $ExpectedPaths.Contains($RelativePath)) {
                throw "Publication contains an unexpected file: $RelativePath"
            }
        }
        Write-Host "Verified publication manifest $ExpectedManifestSha256"
    }
    catch {
        Write-Error -ErrorAction Continue "Deployment publication check failed: $($_.Exception.Message)"
        exit 1
    }
}
#endregion Main Execution
