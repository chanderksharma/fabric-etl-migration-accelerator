#!/usr/bin/env pwsh
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
#Requires -Version 7.0

<#
.SYNOPSIS
    Builds the Windows desktop utility and a portable ZIP package.
.DESCRIPTION
    Builds the React application, restores locked desktop packaging dependencies,
    packages the Python host with PyInstaller in onedir mode, and runs an
    authenticated startup smoke test before creating the ZIP.
.PARAMETER OutputDirectory
    Repository-relative or absolute destination for desktop build outputs.
.PARAMETER SkipWebBuild
    Uses the existing apps/web/dist output instead of rebuilding the React UI.
.PARAMETER SkipSmokeTest
    Skips execution of the packaged startup verification.
.EXAMPLE
    .\scripts\Build-Desktop.ps1
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$OutputDirectory = 'dist\desktop',

    [Parameter(Mandatory = $false)]
    [switch]$SkipWebBuild,

    [Parameter(Mandatory = $false)]
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$OutputRoot = if ([IO.Path]::IsPathRooted($OutputDirectory)) {
    [IO.Path]::GetFullPath($OutputDirectory)
}
else {
    [IO.Path]::GetFullPath((Join-Path $RepositoryRoot $OutputDirectory))
}
$BuildRoot = Join-Path $RepositoryRoot 'build\desktop'
$SpecRoot = Join-Path $BuildRoot 'spec'
$WorkRoot = Join-Path $BuildRoot 'work'
$WebRoot = Join-Path $RepositoryRoot 'apps\web\dist'
$ApplicationName = 'FabricETLMigrationAccelerator'

if (-not $SkipWebBuild) {
    Push-Location (Join-Path $RepositoryRoot 'apps\web')
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Web production build failed' }
    }
    finally {
        Pop-Location
    }
}
if (
    -not (Test-Path -LiteralPath (Join-Path $WebRoot 'index.html') -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $WebRoot 'assets') -PathType Container)
) {
    throw 'The web production build is unavailable'
}

Push-Location $RepositoryRoot
try {
    uv sync --extra dev --extra desktop-build --locked
    if ($LASTEXITCODE -ne 0) { throw 'Desktop packaging dependency restore failed' }

    New-Item -ItemType Directory -Path $OutputRoot, $SpecRoot, $WorkRoot -Force | Out-Null
    uv run --extra desktop-build pyinstaller `
        --noconfirm `
        --clean `
        --onedir `
        --windowed `
        --name $ApplicationName `
        --paths (Join-Path $RepositoryRoot 'src') `
        --add-data "$WebRoot;apps\web\dist" `
        --collect-all webview `
        --copy-metadata pywebview `
        --hidden-import webview.platforms.edgechromium `
        --distpath $OutputRoot `
        --workpath $WorkRoot `
        --specpath $SpecRoot `
        (Join-Path $RepositoryRoot 'src\accelerator\desktop_entry.py')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller desktop build failed' }
}
finally {
    Pop-Location
}

$ApplicationDirectory = Join-Path $OutputRoot $ApplicationName
$Executable = Join-Path $ApplicationDirectory "$ApplicationName.exe"
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "Packaged executable was not created: $Executable"
}

if (-not $SkipSmokeTest) {
    $PriorSmoke = $env:ACCELERATOR_DESKTOP_SMOKE_TEST
    $PriorLocalAppData = $env:LOCALAPPDATA
    $SmokeData = Join-Path $BuildRoot 'smoke-local-app-data'
    try {
        $env:ACCELERATOR_DESKTOP_SMOKE_TEST = '1'
        $env:LOCALAPPDATA = $SmokeData
        $Process = Start-Process -FilePath $Executable -Wait -PassThru
        if ($Process.ExitCode -ne 0) {
            throw "Packaged desktop smoke test failed with exit code $($Process.ExitCode)"
        }
    }
    finally {
        $env:ACCELERATOR_DESKTOP_SMOKE_TEST = $PriorSmoke
        $env:LOCALAPPDATA = $PriorLocalAppData
    }
}

$Archive = Join-Path $OutputRoot "$ApplicationName-windows-x64.zip"
Remove-Item -LiteralPath $Archive -Force -ErrorAction SilentlyContinue
Compress-Archive -LiteralPath $ApplicationDirectory -DestinationPath $Archive -CompressionLevel Optimal

[pscustomobject]@{
    Executable = $Executable
    Archive = $Archive
    DataDirectory = '%LOCALAPPDATA%\Fabric ETL Migration Accelerator'
} | ConvertTo-Json
