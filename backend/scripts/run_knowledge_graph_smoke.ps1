# Knowledge graph governance CLI smoke test.
#
# Runs the whole G1 pipeline (seed -> extract -> review -> publish -> project ->
# verify -> drift -> retire-stale) against a throwaway database, then drops it.
# The dev database is never written to.
#
# ASCII-only on purpose: Windows PowerShell 5.1 reads BOM-less UTF-8 scripts as
# ANSI, so every non-ASCII payload lives in the .py / .json helpers instead.
#
# Usage:  powershell -ExecutionPolicy Bypass -File .\scripts\run_knowledge_graph_smoke.ps1

$ErrorActionPreference = 'Continue'   # alembic logs INFO to stderr; PS 5.1 would treat that as fatal
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'

$backend = Split-Path $PSScriptRoot -Parent
$py = Join-Path $backend '.venv\Scripts\python.exe'
$helper = Join-Path $PSScriptRoot 'knowledge_graph_smoke_db.py'
$seedFile = Join-Path $PSScriptRoot 'knowledge_graph_smoke_concepts.json'
Push-Location $backend

function Invoke-Cli {
    param([string[]]$CliArgs)
    $raw = & $py -m app.knowledge_graph_cli @CliArgs 2>&1 | Out-String
    $code = $LASTEXITCODE
    $json = $null
    try { $json = $raw | ConvertFrom-Json } catch { }
    return [pscustomobject]@{ ExitCode = $code; Json = $json; Raw = $raw.Trim() }
}

$results = [System.Collections.ArrayList]::new()
function Step {
    param([string]$Name, [string[]]$CliArgs, [scriptblock]$Check)
    $r = Invoke-Cli -CliArgs $CliArgs
    $ok = $true
    if ($Check) { $ok = [bool](& $Check $r) }
    [void]$results.Add([pscustomobject]@{ Step = $Name; Exit = $r.ExitCode; Pass = $ok })
    $verdict = 'OK  '
    if (-not $ok) { $verdict = 'FAIL' }
    Write-Host ("[{0}] {1} (exit {2})" -f $verdict, $Name, $r.ExitCode)
    Write-Host ("       {0}" -f $r.Raw)
    return $r
}

try {
    Write-Host '--- 1. throwaway database + migrations ---'
    & $py $helper create
    $env:POSTGRES_DB = 'kg_cli_smoke'
    & $py -m alembic upgrade head 2>&1 | Select-String -Pattern 'Running upgrade|ERROR' | ForEach-Object { $_.Line.Trim() }
    if ($LASTEXITCODE -ne 0) { throw "alembic upgrade failed with exit $LASTEXITCODE" }

    Write-Host '--- 2. seed an approved document ---'
    $docId = (& $py $helper seed | Select-Object -Last 1).Trim()
    Write-Host "document: $docId"

    Write-Host '--- 3. governance CLI walkthrough ---'
    $null = Step 'seed-concepts' @('seed-concepts', '--file', $seedFile) {
        param($x) $x.ExitCode -eq 0 -and @($x.Json.result).Count -eq 6
    }
    $null = Step 'extract-candidates' @('extract-candidates', '--document', $docId) {
        param($x) $x.ExitCode -eq 0 -and $x.Json.result.candidates_created -eq 5 -and @($x.Json.result.chunks_without_concepts).Count -eq 1
    }
    $queue = Step 'review-queue' @('review-queue', '--limit', '10') {
        param($x) $x.ExitCode -eq 0 -and @($x.Json.result).Count -eq 5 -and $x.Json.result[0].publishable
    }
    foreach ($item in $queue.Json.result) {
        $label = "approve-claim {0}->{1}" -f $item.subject_name, $item.object_name
        $null = Step $label @('approve-claim', '--claim', $item.claim_id, '--actor', 'reviewer-smoke', '--note', 'matches-source') {
            param($x) $x.ExitCode -eq 0 -and $x.Json.result.status -eq 'reviewed'
        }
    }
    $published = Step 'publish' @('publish', '--actor', 'reviewer-smoke') {
        param($x) $x.ExitCode -eq 0 -and $x.Json.result.revision -eq 1 -and $x.Json.result.claim_count -eq 5
    }
    $jobId = $published.Json.result.job_id
    $null = Step 'status' @('status') {
        param($x) $x.ExitCode -eq 0 -and $x.Json.result.claims_by_status.published -eq 5 -and $x.Json.result.evidence_rows -eq 5
    }
    $null = Step 'verify (before projection)' @('verify') {
        param($x) $x.ExitCode -eq 0 -and $x.Json.result.ok -and $x.Json.result.report.revision_in_sync -eq $false
    }
    $null = Step 'claim-job' @('claim-job', '--owner', 'smoke-worker', '--lease-seconds', '60') {
        param($x) $x.ExitCode -eq 0 -and $x.Json.result.target_revision -eq 1 -and $x.Json.result.attempts -eq 1
    }
    $null = Step 'complete-job' @('complete-job', '--job', $jobId, '--owner', 'smoke-worker') {
        param($x) $x.ExitCode -eq 0
    }
    $null = Step 'publication-status' @('publication-status') {
        param($x) $x.ExitCode -eq 0 -and $x.Json.result.last_published_revision -eq 1
    }
    $null = Step 'verify (after projection)' @('verify') {
        param($x) $x.ExitCode -eq 0 -and $x.Json.result.ok -and $x.Json.result.report.revision_in_sync
    }
    $null = Step 'approve-unknown-claim fails' @('approve-claim', '--claim', [guid]::NewGuid().ToString(), '--actor', 'reviewer-smoke') {
        param($x) $x.ExitCode -eq 1 -and -not $x.Json.ok
    }
    $null = Step 'publish again is idempotent' @('publish', '--actor', 'reviewer-smoke') {
        param($x) $x.ExitCode -eq 1 -and -not $x.Json.ok
    }

    Write-Host '--- 3b. source text drift: verify must fail, retire-stale must fix it ---'
    & $py $helper drift
    $null = Step 'verify detects drift (exit 1)' @('verify') {
        param($x) $x.ExitCode -eq 1 -and -not $x.Json.result.ok -and ($x.Json.result.report.issues | Where-Object { $_.code -eq 'EVIDENCE_HASH_MISMATCH' })
    }
    $null = Step 'retire-stale retires all 5' @('retire-stale', '--actor', 'reviewer-smoke') {
        param($x) $x.ExitCode -eq 0 -and $x.Json.result.retired_count -eq 5
    }
    $null = Step 'verify clean again' @('verify') {
        param($x) $x.ExitCode -eq 0 -and $x.Json.result.ok
    }
    $null = Step 'retire-stale finds nothing now' @('retire-stale', '--actor', 'reviewer-smoke') {
        param($x) $x.ExitCode -eq 0 -and $x.Json.result.retired_count -eq 0
    }
}
finally {
    Write-Host '--- 4. cleanup ---'
    Remove-Item Env:\POSTGRES_DB -ErrorAction SilentlyContinue
    & $py $helper drop
    Pop-Location
}

Write-Host ''
Write-Host '=== smoke summary ==='
$results | Format-Table -AutoSize
$failed = @($results | Where-Object { -not $_.Pass }).Count
Write-Host ("failed steps: {0} / {1}" -f $failed, $results.Count)
if ($failed -gt 0) { exit 1 }