#!/usr/bin/env pwsh
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
#Requires -Version 7.0

<#
.SYNOPSIS
    Builds the Windows desktop utility and a portable ZIP package from built Python wheels.
.DESCRIPTION
    Builds the React application, builds all workspace Python wheels (.whl),
    installs the wheels and locked desktop packaging dependencies into an isolated
    build virtual environment, packages the Python host with PyInstaller in onedir
    mode, and runs an authenticated startup smoke test before creating the ZIP.
.PARAMETER OutputDirectory
    Repository-relative or absolute destination for desktop build outputs.
.PARAMETER SkipWebBuild
    Uses the existing apps/web/dist output instead of rebuilding the React UI.
.PARAMETER SkipWheelBuild
    Uses existing workspace .whl files under dist/ instead of running uv build.
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
    [switch]$SkipWheelBuild,

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
$DesktopVenv = Join-Path $BuildRoot 'venv'
$DistRoot = Join-Path $RepositoryRoot 'dist'
$WebRoot = Join-Path $RepositoryRoot 'apps\web\dist'
$ApplicationName = 'FabricETLMigrationAccelerator'

$WheelPatterns = @(
    'etl_migration_core-*.whl',
    'etl_portfolio_assessment-*.whl',
    'etl_target_fabric-*.whl',
    'fabric_etl_migration_accelerator-*.whl'
)

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
    if (-not $SkipWheelBuild) {
        if (Test-Path -LiteralPath $DistRoot -PathType Container) {
            foreach ($Pattern in $WheelPatterns) {
                Get-ChildItem -LiteralPath $DistRoot -Filter $Pattern -File | Remove-Item -Force
            }
        }
        uv build --all-packages --wheel
        if ($LASTEXITCODE -ne 0) { throw 'Workspace wheel build failed' }
    }

    $ResolvedWheels = [System.Collections.Generic.List[string]]::new()
    foreach ($Pattern in $WheelPatterns) {
        $Latest = Get-ChildItem -LiteralPath $DistRoot -Filter $Pattern -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
        if (-not $Latest) {
            throw "Missing built wheel matching '$Pattern' in $DistRoot"
        }
        $ResolvedWheels.Add($Latest.FullName)
    }

    $PriorUvProjectEnv = $env:UV_PROJECT_ENVIRONMENT
    try {
        $env:UV_PROJECT_ENVIRONMENT = $DesktopVenv
        uv sync --extra desktop-build --no-dev --locked --no-editable
        if ($LASTEXITCODE -ne 0) { throw 'Desktop packaging dependency restore failed' }
    }
    finally {
        $env:UV_PROJECT_ENVIRONMENT = $PriorUvProjectEnv
    }

    $DesktopPython = Join-Path $DesktopVenv 'Scripts\python.exe'
    $DesktopPyInstaller = Join-Path $DesktopVenv 'Scripts\pyinstaller.exe'
    if (-not (Test-Path -LiteralPath $DesktopPython -PathType Leaf)) {
        throw "Isolated desktop venv python not found: $DesktopPython"
    }

    uv pip install --python $DesktopPython --no-deps --force-reinstall @ResolvedWheels
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install built wheels into desktop packaging environment' }

    New-Item -ItemType Directory -Path $OutputRoot, $SpecRoot, $WorkRoot -Force | Out-Null
    $LauncherScript = Join-Path $WorkRoot 'desktop_launcher.py'
    @(
        'from accelerator.desktop.window import desktop_entry'
        ''
        'if __name__ == "__main__":'
        '    raise SystemExit(desktop_entry())'
    ) | Set-Content -LiteralPath $LauncherScript -Encoding utf8

    & $DesktopPyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --windowed `
        --name $ApplicationName `
        --add-data "$WebRoot;apps\web\dist" `
        --collect-all webview `
        --collect-submodules etl_target_fabric `
        --copy-metadata pywebview `
        --copy-metadata etl-migration-core `
        --copy-metadata etl-portfolio-assessment `
        --copy-metadata etl-target-fabric `
        --copy-metadata fabric-etl-migration-accelerator `
        --hidden-import webview.platforms.edgechromium `
        --hidden-import etl_target_fabric.provider `
        --distpath $OutputRoot `
        --workpath $WorkRoot `
        --specpath $SpecRoot `
        $LauncherScript
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
