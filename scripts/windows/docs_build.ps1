#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path "$ScriptDir\..\.."
$DocsDir   = Join-Path $RepoRoot "docs"

Set-Location $DocsDir

if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 pnpm。请先安装: npm install -g pnpm"
    exit 1
}

pnpm install --frozen-lockfile
pnpm build

Write-Host "Build complete: $DocsDir\.vitepress\dist"
