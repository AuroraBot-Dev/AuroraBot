#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path "$ScriptDir\..\.."
$PanelDir  = Join-Path $RepoRoot "panel"

Set-Location $PanelDir

if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 pnpm。请先安装: npm install -g pnpm"
    exit 1
}

try {
    $null = Invoke-WebRequest -Uri "http://127.0.0.1:8765/healthz" -TimeoutSec 2 -UseBasicParsing
}
catch {
    Write-Warning "AuroraBot 后端不可达: http://127.0.0.1:8765。请先在仓库根目录运行 uv run aurora start 启动后端。"
}

pnpm install --frozen-lockfile
pnpm dev
