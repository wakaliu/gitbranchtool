# 一键构建 Windows：便携 onefile exe + Inno Setup 安装包（若本机已安装 ISCC）。
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

# 公开安装包链路：禁止误用内部版环境变量
Remove-Item Env:\GITTOOL_SAUSAGE_INTERNAL -ErrorAction SilentlyContinue

python -m pip install -U pip wheel
pip install -r requirements.txt pyinstaller
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
python -m pip uninstall -y typing 2>&1 | Out-Null
$ErrorActionPreference = $prevEap

$workWin = Join-Path $Root "packaging\pyinstaller\work-win"
$specWin = Join-Path $Root "packaging\pyinstaller\GitPullSwitchTool_windows.spec"
$distOut = Join-Path $Root "dist"

pyinstaller --noconfirm --clean --distpath $distOut --workpath $workWin $specWin

python (Join-Path $Root "scripts\package_windows_zip.py") --dist-dir $distOut

. (Join-Path $Root "scripts\inno_setup.ps1")
$issPublic = Join-Path $Root "packaging\windows\GitPullSwitchTool.iss"
if (-not (Test-Path (Join-Path $distOut "GitPullSwitchTool.exe"))) {
    throw "Portable exe missing before Inno: $distOut\GitPullSwitchTool.exe"
}
Invoke-InnoSetupBuild -IssPath $issPublic -Label "public"
Write-Host "安装包目录: $distOut\windows-installer\"
