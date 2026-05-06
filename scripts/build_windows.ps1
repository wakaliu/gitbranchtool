# 一键构建 Windows：便携 onefile exe + Inno Setup 安装包（若本机已安装 ISCC）。
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

# 公开安装包链路：禁止误用内部版环境变量
Remove-Item Env:\GITTOOL_SAUSAGE_INTERNAL -ErrorAction SilentlyContinue

python -m pip install -U pip wheel
pip install -r requirements.txt pyinstaller

$workWin = Join-Path $Root "packaging\pyinstaller\work-win"
$specWin = Join-Path $Root "packaging\pyinstaller\GitPullSwitchTool_windows.spec"
$distOut = Join-Path $Root "dist"

pyinstaller --noconfirm --clean --distpath $distOut --workpath $workWin $specWin

python (Join-Path $Root "scripts\package_windows_zip.py") --dist-dir $distOut

$iss = Join-Path $Root "packaging\windows\GitPullSwitchTool.iss"
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($iscc) {
    & $iscc $iss
    Write-Host "安装包: dist\windows-installer\"
} else {
    Write-Warning "Inno Setup 6 (ISCC.exe) not found; skipped installer. Portable exe: dist\GitPullSwitchTool.exe"
}
