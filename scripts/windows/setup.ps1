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

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 uv。请先安装 uv，参见 https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
}

if (-not (Confirm-Action "确认将 aurora 安装到用户工具目录 $ToolBin 吗？")) {
    Write-Host "已取消安装，脚本退出。"
    exit 1
}

uv tool install --editable --force $RepoRoot
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

if (Get-Command aurora -ErrorAction SilentlyContinue) {
    aurora --root $RepoRoot setup
} else {
    & "$ToolBin\aurora.exe" --root $RepoRoot setup
}
exit $LASTEXITCODE
