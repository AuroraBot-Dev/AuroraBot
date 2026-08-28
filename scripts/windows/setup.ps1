#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path "$ScriptDir\..\.."
$ToolBin   = Join-Path $env:USERPROFILE ".local\bin"

function Confirm-Action([string]$Message) {
    $answer = Read-Host "$Message [Y/N]（回车默认 Y）"
    return [string]::IsNullOrWhiteSpace($answer) -or $answer -match "^[Yy]"
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 git。请先安装 git。"
    exit 1
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 uv。请先安装 uv，参见 https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
}
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 pnpm。请先安装: npm install -g pnpm"
    exit 1
}

$linked = $false
if (Confirm-Action "确认将 aurora 全局链接到用户工具目录 $ToolBin（editable，不复制项目）吗？") {
    $linked = $true
    $tomlContent = Get-Content "$RepoRoot\pyproject.toml" -Raw
    $indexUrl = if ($tomlContent -match 'index-url\s*=\s*"([^"]+)"') { $Matches[1] } else { "" }
    if ($indexUrl) {
        uv tool install --editable --force --index-url $indexUrl $RepoRoot
    } else {
        uv tool install --editable --force $RepoRoot
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $needsPathUpdate = ($userPath -split ";") -notcontains $ToolBin
    if ($needsPathUpdate) {
        if (Confirm-Action "确认将 $ToolBin 写入用户 PATH（修改注册表）吗？") {
            $newPath = if ([string]::IsNullOrEmpty($userPath)) { $ToolBin } else { "$ToolBin;$userPath" }
            [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
            Write-Host "已将 $ToolBin 加入用户 PATH，新终端可直接使用 aurora。"
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
        } else {
            Write-Host "已跳过用户 PATH 写入；将使用完整路径调用 aurora，新终端暂时无法直接使用 aurora。"
        }
    }
} else {
    Write-Host "已跳过全局链接；将使用仓库本地虚拟环境完成引导。"
}

if (Get-Command aurora -ErrorAction SilentlyContinue) {
    aurora --root $RepoRoot setup
} elseif ($linked) {
    & "$ToolBin\aurora.exe" --root $RepoRoot setup
} else {
    uv run --project $RepoRoot aurora --root $RepoRoot setup
}
exit $LASTEXITCODE
