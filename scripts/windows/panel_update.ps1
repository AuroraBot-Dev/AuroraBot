#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path "$ScriptDir\..\.."
$PanelDir  = Join-Path $RepoRoot "panel"

$gitFile = Join-Path $PanelDir ".git"
if ((Test-Path $gitFile)) {
    git -C $PanelDir diff --quiet 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "panel 子模块有未提交的更改。请先提交或暂存后再更新。"
        exit 1
    }
}

git -C $RepoRoot submodule update --init --remote panel

git -C $RepoRoot diff --quiet -- panel
if ($LASTEXITCODE -ne 0) {
    Write-Warning "panel 子模块指针已变更。请在 AuroraBot 仓库中提交: git add panel && git commit"
}

Set-Location $PanelDir

if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 pnpm。请先安装: npm install -g pnpm"
    exit 1
}

pnpm install

Write-Host "Update complete: $PanelDir"
