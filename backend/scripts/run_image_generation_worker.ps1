$ErrorActionPreference = 'Stop'

$backendDirectory = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $backendDirectory '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw "Backend virtual-environment Python was not found: $pythonExecutable"
}

Push-Location -LiteralPath $backendDirectory
try {
    & $pythonExecutable -m app.image_generation_cli --limit 20
    if ($LASTEXITCODE -ne 0) {
        throw "Image-generation worker exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
