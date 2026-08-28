#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path "$ScriptDir\..\.."
$PanelDir  = Join-Path $RepoRoot "panel"

git -C $RepoRoot submodule update --init panel

Set-Location $PanelDir

if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 pnpm。请先安装: npm install -g pnpm"
    exit 1
}

pnpm install --frozen-lockfile

Write-Host "Setup complete: $PanelDir"
