#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path "$ScriptDir\..\.."
$PanelDir  = Join-Path $RepoRoot "panel"

Set-Location $PanelDir

if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Error "pnpm is not installed. Install it with: npm install -g pnpm"
    exit 1
}

if (-not (Test-Path "node_modules")) {
    Write-Error "Dependencies are missing. Run scripts\windows\panel_setup.ps1 first."
    exit 1
}

pnpm build

Write-Host "Build complete: $PanelDir\apps\web\dist"
