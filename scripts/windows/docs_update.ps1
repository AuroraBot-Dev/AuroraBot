#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path "$ScriptDir\..\.."
$DocsDir   = Join-Path $RepoRoot "docs"

$gitFile = Join-Path $DocsDir ".git"
if ((Test-Path $gitFile)) {
    git -C $DocsDir diff --quiet 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "docs 子模块有未提交的更改。请先提交或暂存后再更新。"
        exit 1
    }
}

git -C $RepoRoot submodule update --init --remote docs

git -C $RepoRoot diff --quiet -- docs
if ($LASTEXITCODE -ne 0) {
    Write-Warning "docs 子模块指针已变更。请在 AuroraBot 仓库中提交: git add docs && git commit"
}

Set-Location $DocsDir

if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 pnpm。请先安装: npm install -g pnpm"
    exit 1
}

pnpm install

Write-Host "Update complete: $DocsDir"
