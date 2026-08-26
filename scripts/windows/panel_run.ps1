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

try {
    $null = Invoke-WebRequest -Uri "http://127.0.0.1:8765/healthz" -TimeoutSec 2 -UseBasicParsing
}
catch {
    Write-Warning "AuroraBot backend is not reachable at http://127.0.0.1:8765. Start it with 'uv run aurora start' in the repository root first."
}

pnpm dev
