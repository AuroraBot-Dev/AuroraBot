#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path "$ScriptDir\..\.."
$DocsDir   = Join-Path $RepoRoot "docs"

git -C $RepoRoot submodule update --init --remote docs

git -C $RepoRoot diff --quiet -- docs
if ($LASTEXITCODE -ne 0) {
    Write-Warning "docs submodule pointer changed. Commit it in the AuroraBot repository: git add docs && git commit"
}

Set-Location $DocsDir

if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Error "pnpm is not installed. Install it with: npm install -g pnpm"
    exit 1
}

pnpm install

Write-Host "Update complete: $DocsDir"
