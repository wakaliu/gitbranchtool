# Dual Windows onefile: public (no embedded sausage_projects) + internal (embed repo-root yaml; do not commit yaml).
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

python -m pip install -U pip wheel
pip install -r requirements.txt pyinstaller

$specWin = Join-Path $Root "packaging\pyinstaller\GitPullSwitchTool_windows.spec"
$pkgZip = Join-Path $Root "scripts\package_windows_zip.py"

# Public build (default for CI/Release): no embedded sausage_projects.yaml
Remove-Item Env:\GITTOOL_SAUSAGE_INTERNAL -ErrorAction SilentlyContinue
$workPublic = Join-Path $Root "packaging\pyinstaller\work-win-public"
$distPublic = Join-Path $Root "dist"
pyinstaller --noconfirm --clean --distpath $distPublic --workpath $workPublic $specWin
python $pkgZip --dist-dir $distPublic --exe-name GitPullSwitchTool.exe
Write-Host "Public build: $distPublic\GitPullSwitchTool.exe"

# Internal build: requires repo-root sausage_projects.yaml (.gitignore)
$rootYaml = Join-Path $Root "sausage_projects.yaml"
if (-not (Test-Path $rootYaml)) {
    Write-Warning "Missing $rootYaml ; skipped internal build. Add file at repo root and re-run."
    exit 0
}

$env:GITTOOL_SAUSAGE_INTERNAL = "1"
$workSausage = Join-Path $Root "packaging\pyinstaller\work-win-sausage"
$distSausage = Join-Path $Root "dist"
pyinstaller --noconfirm --clean --distpath $distSausage --workpath $workSausage $specWin
python $pkgZip --dist-dir $distSausage --exe-name GitPullSwitchTool-Sausage.exe --internal
Remove-Item Env:\GITTOOL_SAUSAGE_INTERNAL -ErrorAction SilentlyContinue
Write-Host "Internal (Sausage) build: $distSausage\GitPullSwitchTool-Sausage.exe"
