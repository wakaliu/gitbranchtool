# Shared Inno Setup (ISCC) helpers for Windows build scripts.

function Resolve-InnoSetupCompiler {
    <#
    .SYNOPSIS
    Locate Inno Setup 6 compiler (ISCC.exe) on Windows.
    #>
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) {
            return $path
        }
    }
    return $null
}

function Invoke-InnoSetupBuild {
    <#
    .SYNOPSIS
    Compile an Inno Setup script; fails the script when ISCC is missing or compile fails.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$IssPath,
        [string]$Label = "installer"
    )
    $iscc = Resolve-InnoSetupCompiler
    if (-not $iscc) {
        throw "Inno Setup 6 (ISCC.exe) not found. Install from https://jrsoftware.org/isinfo.php or run: choco install innosetup -y"
    }
    if (-not (Test-Path $IssPath)) {
        throw "Inno script not found: $IssPath"
    }
    & $iscc $IssPath
    if ($LASTEXITCODE -ne 0) {
        throw "ISCC failed ($Label): $IssPath (exit $LASTEXITCODE)"
    }
    Write-Host "Inno Setup OK ($Label): $IssPath"
}
