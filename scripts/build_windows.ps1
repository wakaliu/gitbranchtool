# 一键构建 Windows：便携 onefile exe + Inno Setup 安装包（若本机已安装 ISCC）。
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

python -m pip install -U pip wheel
pip install -r requirements.txt pyinstaller

$workWin = Join-Path $Root "packaging\pyinstaller\work-win"
$specWin = Join-Path $Root "packaging\pyinstaller\GitPullSwitchTool_windows.spec"
$distPortable = Join-Path $Root "dist\windows-portable"

pyinstaller --noconfirm --clean --distpath $distPortable --workpath $workWin $specWin

$iss = Join-Path $Root "packaging\windows\GitPullSwitchTool.iss"
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($iscc) {
    & $iscc $iss
    Write-Host "安装包: dist\windows-installer\"
} else {
    Write-Warning "未找到 Inno Setup 6 (ISCC.exe)，已跳过安装包。便携程序: dist\windows-portable\GitPullSwitchTool.exe"
}
