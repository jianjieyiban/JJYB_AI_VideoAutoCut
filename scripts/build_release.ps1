param(
    [string]$Version = "3.4.0"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DistDir = Join-Path $ProjectRoot "dist"
$ArchiveName = "JJYB_AI_VideoAutoCut-v$Version-source.zip"
$ArchivePath = Join-Path $DistDir $ArchiveName

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required to build the source archive."
}

New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
if (Test-Path -LiteralPath $ArchivePath) {
    Remove-Item -LiteralPath $ArchivePath -Force
}

Push-Location $ProjectRoot
try {
    git archive --format=zip --output=$ArchivePath --prefix="JJYB_AI_VideoAutoCut-v$Version/" HEAD
    if ($LASTEXITCODE -ne 0) {
        throw "git archive failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ArchivePath).Hash.ToLowerInvariant()
Write-Host "Release archive: $ArchivePath"
Write-Host "SHA256: $Hash"
