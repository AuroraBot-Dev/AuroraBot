#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path "$ScriptDir\..\.."
$PanelDir  = Join-Path $RepoRoot "panel"

git -C $RepoRoot submodule update --init --remote panel

git -C $RepoRoot diff --quiet -- panel
if ($LASTEXITCODE -ne 0) {
    Write-Warning "panel submodule pointer changed. Commit it in the AuroraBot repository: git add panel && git commit"
}

Set-Location $PanelDir

if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Error "pnpm is not installed. Install it with: npm install -g pnpm"
    exit 1
}

pnpm install

Write-Host "Update complete: $PanelDir"
