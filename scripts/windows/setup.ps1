#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# 保留 UTF-8 BOM，确保 PowerShell 5.1 正确解码中文源码。
$Utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $Utf8
[Console]::OutputEncoding = $Utf8
$OutputEncoding = $Utf8

& node (Join-Path $PSScriptRoot "..\setup.ts") @args
exit $LASTEXITCODE
