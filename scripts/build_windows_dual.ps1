# Dual Windows onefile: public (no embedded sausage_projects) + internal (embed repo-root yaml; do not commit yaml).
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

python -m pip install -U pip wheel
pip install -r requirements.txt pyinstaller
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
python -m pip uninstall -y typing 2>&1 | Out-Null
$ErrorActionPreference = $prevEap

$specWin = Join-Path $Root "packaging\pyinstaller\GitPullSwitchTool_windows.spec"
$pkgZip = Join-Path $Root "scripts\package_windows_zip.py"

# Public build (default for CI/Release): no embedded sausage_projects.yaml
Remove-Item Env:\GITTOOL_SAUSAGE_INTERNAL -ErrorAction SilentlyContinue
$workPublic = Join-Path $Root "packaging\pyinstaller\work-win-public"
$distPublic = Join-Path $Root "dist"
pyinstaller --noconfirm --clean --distpath $distPublic --workpath $workPublic $specWin
python $pkgZip --dist-dir $distPublic --exe-name GitPullSwitchTool.exe
Write-Host "Public build: $distPublic\GitPullSwitchTool.exe"

# Internal: embed repo-root sausage_projects.yaml (gitignored). If missing, copy bundle template for this run only.
$rootYaml = Join-Path $Root "sausage_projects.yaml"
$templateYaml = Join-Path $Root "src\git_gui\bundle_data\sausage_projects.yaml"
$tempInternalYaml = $false
if (-not (Test-Path $rootYaml)) {
    if (-not (Test-Path $templateYaml)) {
        Write-Warning "Missing sausage_projects.yaml and bundle template; skipped internal build."
        exit 0
    }
    Copy-Item -Force $templateYaml $rootYaml
    $tempInternalYaml = $true
    Write-Warning "Using bundle template as temporary sausage_projects.yaml for internal build; file will be removed after."
}

$env:GITTOOL_SAUSAGE_INTERNAL = "1"
$workSausage = Join-Path $Root "packaging\pyinstaller\work-win-sausage"
$distSausage = Join-Path $Root "dist"
pyinstaller --noconfirm --clean --distpath $distSausage --workpath $workSausage $specWin
python $pkgZip --dist-dir $distSausage --exe-name GitPullSwitchTool-Sausage.exe --internal
Remove-Item Env:\GITTOOL_SAUSAGE_INTERNAL -ErrorAction SilentlyContinue
if ($tempInternalYaml) {
    Remove-Item -Force $rootYaml
    Write-Host "Removed temporary sausage_projects.yaml"
}
Write-Host "Internal (Sausage) build: $distSausage\GitPullSwitchTool-Sausage.exe"
