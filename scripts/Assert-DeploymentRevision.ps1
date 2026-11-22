#!/usr/bin/env pwsh
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
#Requires -Version 7.0

<#
.SYNOPSIS
    Check that the CI event and checkout match the requested deployment commit.
.DESCRIPTION
    Fails before deployment if the selected reference resolved to another commit.
.PARAMETER ExpectedCommit
    Full lowercase commit SHA requested by the caller.
.PARAMETER SourceCommit
    Full commit SHA reported by the CI platform.
.EXAMPLE
    ./scripts/Assert-DeploymentRevision.ps1 -ExpectedCommit $expected -SourceCommit $env:GITHUB_SHA
.NOTES
    This check does not verify artifact provenance or the integrity of the CI definition.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ExpectedCommit,

    [Parameter(Mandatory = $true)]
    [AllowEmptyString()]
    [string]$SourceCommit
)

$ErrorActionPreference = 'Stop'

#region Main Execution
if ($MyInvocation.InvocationName -ne '.') {
    try {
        $CheckoutCommit = git rev-parse --verify HEAD
        if ($LASTEXITCODE -ne 0) {
            throw 'Cannot determine the checked-out commit'
        }
        if ($SourceCommit -cne $ExpectedCommit -or $CheckoutCommit -cne $ExpectedCommit) {
            throw 'Deployment revision does not match the requested commit'
        }
        Write-Host "Verified deployment revision $ExpectedCommit"
    }
    catch {
        Write-Error -ErrorAction Continue "Deployment revision check failed: $($_.Exception.Message)"
        exit 1
    }
}
#endregion Main Execution
