#Requires -RunAsAdministrator
param([Parameter(Mandatory = $true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'

# Explicitly authorized on 2026-10-21. Change one BCD setting; never reboot.
$perfBcd = Join-Path $env:WINDIR 'System32\bcdedit.exe'
$perfCurrent = '{current}'
$perfBefore = @(& $perfBcd /enum $perfCurrent 2>&1 | ForEach-Object { [string]$_ })
if ($LASTEXITCODE -ne 0) { throw 'Unable to read current boot configuration' }
$perfOutput = [System.IO.Path]::GetFullPath($OutputPath)
$perfStream = [System.IO.File]::Open($perfOutput, [System.IO.FileMode]::CreateNew)
$perfWriter = [System.IO.StreamWriter]::new($perfStream, [System.Text.UTF8Encoding]::new($false))
try {
    $perfSetResult = @(& $perfBcd /set hypervisorlaunchtype auto 2>&1 |
        ForEach-Object { [string]$_ })
    $perfSetExit = $LASTEXITCODE
    $perfAfter = @(& $perfBcd /enum $perfCurrent 2>&1 | ForEach-Object { [string]$_ })
    $perfReadExit = $LASTEXITCODE
    $perfVerified = ($perfSetExit -eq 0 -and $perfReadExit -eq 0 -and
        (($perfAfter -join "`n") -match '(?im)^hypervisorlaunchtype\s+Auto\s*$'))
    $perfReport = @{
        completedAt = (Get-Date).ToString('o')
        command = 'bcdedit /set hypervisorlaunchtype auto'
        before = $perfBefore
        setExitCode = $perfSetExit
        setOutput = $perfSetResult
        after = $perfAfter
        verifiedAuto = $perfVerified
        restartPerformed = $false
    }
    $perfWriter.Write(($perfReport | ConvertTo-Json -Depth 5))
    $perfWriter.Flush()
    if (-not $perfVerified) { throw 'Boot setting could not be verified; inspect saved report' }
} finally {
    $perfWriter.Dispose()
}
