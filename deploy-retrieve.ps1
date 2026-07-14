<#
deploy-retrieve.ps1
Purpose: Backup Postgres, create/apply alembic migration inside api container,
         enqueue a smoke retrieval job, verify DB/Redis, and optionally start worker/api.
Assumptions:
 - docker and docker compose are available on PATH.
 - Compose service names include 'api', 'worker', 'postgres', 'redis' (adjust if different).
 - Postgres container name is discoverable by image filter or is 'tier2-postgres-1'.
 - The API exposes port 8010 in compose (adjust if different).
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Pause-Checkpoint($msg) {
    Write-Host "`n=== CHECKPOINT === $msg ===`n" -ForegroundColor Cyan
    $resp = Read-Host "Type 'y' to continue, anything else to abort"
    if ($resp -ne 'y') {
        Write-Host "Aborting at checkpoint." -ForegroundColor Yellow
        exit 1
    }
}

function Run-Local($cmd, $failMsg) {
    Write-Host ">> $cmd" -ForegroundColor DarkGray
    # Run the command in a new PowerShell process and capture combined output
    $out = & powershell -NoProfile -Command $cmd 2>&1
    $exit = $LASTEXITCODE
    if ($exit -ne 0) {
        Write-Host "ERROR: $failMsg" -ForegroundColor Red
        Write-Host $out
        throw "Command failed with exit code $exit"
    }
    return $out
}

function Run-DockerCompose($args, $failMsg) {
    $cmd = "docker compose $args"
    return Run-Local $cmd $failMsg
}

# --- Step 0: Quick sanity checks
Write-Host "Step 0: Sanity checks" -ForegroundColor Green
Run-Local "docker info" "Docker daemon not reachable. Start Docker Desktop and retry."
Run-Local "docker compose ps" "docker compose ps failed. Ensure you are in the compose project root."

# Show current compose ps for operator
Run-Local "docker compose ps --format 'table {{.Names}}\t{{.Service}}\t{{.Status}}'" "Failed to list compose services."

Pause-Checkpoint "Confirm the output above shows Postgres and Redis Up and api/worker stopped (or you are ready to proceed)."

# --- Step 1: Ensure backups folder exists and create Postgres dump
Write-Host "Step 1: Create backups folder and dump Postgres" -ForegroundColor Green
New-Item -ItemType Directory -Path .\backups -Force | Out-Null

# Detect postgres container name (prefer compose image filter)
$pgContainer = (docker ps --filter "ancestor=postgres" --format "{{.Names}}" | Select-Object -First 1)
if (-not $pgContainer) {
    Write-Host "No postgres container found by image filter. Trying common compose name 'tier2-postgres-1'." -ForegroundColor Yellow
    $pgContainer = "tier2-postgres-1"
}

Write-Host "Using Postgres container: $pgContainer" -ForegroundColor Cyan
Pause-Checkpoint "Confirm the Postgres container name above is correct."

$timestamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
$backupFile = ".\backups\pg_backup_$timestamp.sql"

Write-Host "Creating logical dump to $backupFile" -ForegroundColor Green
# Use docker exec to run pg_dumpall inside container and redirect to host file via cmd.exe
$dumpCmd = "docker exec -t $pgContainer pg_dumpall -U postgres > `"$backupFile`""
Run-Local "cmd /c `"$dumpCmd`"" "Failed to create Postgres dump. Confirm container name and that pg_dumpall is available."

Write-Host "Backup created:" -ForegroundColor Green
Get-ChildItem .\backups | Sort-Object LastWriteTime -Descending | Select-Object -First 3 | Format-Table

Pause-Checkpoint "Confirm backup file exists and is non-zero."

# --- Step 2: Create Alembic migration inside api container
Write-Host "Step 2: Create Alembic migration inside the api container" -ForegroundColor Green
$revisionMessage = "add retrieval_jobs table"
Run-DockerCompose "run --rm api python -m alembic revision --autogenerate -m `"$revisionMessage`"" "Failed to create alembic revision inside api container."

Write-Host "Listing alembic/versions (if present) for review:" -ForegroundColor Cyan
if (Test-Path .\alembic\versions) {
    Get-ChildItem .\alembic\versions | Sort-Object LastWriteTime -Descending | Select-Object -First 5 | Format-Table
} else {
    Write-Host "No alembic/versions directory found in repo root. If your project stores migrations elsewhere, inspect that location." -ForegroundColor Yellow
}

Pause-Checkpoint "Open and review the new Alembic migration file now. Confirm it creates the retrieval_jobs table as expected."

# --- Step 3: Apply migration
Write-Host "Step 3: Apply Alembic migration (upgrade head) inside api container" -ForegroundColor Green
Run-DockerCompose "run --rm api python -m alembic upgrade head" "Failed to apply alembic migrations inside api container."

Write-Host "Migration applied. Verify retrieval_jobs table exists in Postgres." -ForegroundColor Green
Run-Local "docker exec -i $pgContainer psql -U postgres -d postgres -c `"\\dt retrieval_jobs*`"" "Failed to query Postgres for retrieval_jobs table."

Pause-Checkpoint "Confirm retrieval_jobs table exists and schema looks correct."

# --- Step 4: Enqueue a smoke /retrieve job via API (202 Accepted expected)
Write-Host "Step 4: Enqueue smoke /retrieve job" -ForegroundColor Green
$apiHost = "http://localhost:8010"
$smokePayload = @{ claim = "Smoke test claim"; source_language = "en"; ingest_id = "smoke-test-$(Get-Random -Maximum 99999)"; context = "smoke test" } | ConvertTo-Json
Write-Host "Payload: $smokePayload" -ForegroundColor DarkGray

# Try curl first, fallback to Invoke-RestMethod
$curlAvailable = $false
try {
    & curl --version > $null 2>&1
    $curlAvailable = $true
} catch { $curlAvailable = $false }

if ($curlAvailable) {
    $curlCmd = "curl -s -X POST $apiHost/retrieve -H `"Content-Type: application/json`" -d `'$smokePayload`'"
    $curlOut = Run-Local $curlCmd "Failed to POST to API using curl."
    Write-Host "API response (curl): $curlOut" -ForegroundColor Green
} else {
    try {
        $resp = Invoke-RestMethod -Uri "$apiHost/retrieve" -Method Post -Body $smokePayload -ContentType "application/json" -ErrorAction Stop
        Write-Host "API response (Invoke-RestMethod):" -ForegroundColor Green
        $resp | ConvertTo-Json -Depth 5
    } catch {
        Write-Host "Failed to POST to API. Ensure API is reachable at $apiHost or start it after verifying." -ForegroundColor Red
        Write-Host $_.Exception.Message
    }
}

Pause-Checkpoint "If the API returned a job_id and status queued, continue. Otherwise inspect API logs and network."

# --- Step 5: Verify DB row and Redis queue
Write-Host "Step 5: Verify retrieval_jobs row and Redis queue" -ForegroundColor Green
Run-Local "docker exec -i $pgContainer psql -U postgres -d postgres -c `"SELECT id, ingest_id, status, created_at FROM retrieval_jobs ORDER BY created_at DESC LIMIT 5;`"" "Failed to query retrieval_jobs."

$redisContainer = (docker ps --filter "ancestor=redis" --format "{{.Names}}" | Select-Object -First 1)
if (-not $redisContainer) { $redisContainer = "tier2-redis-1" }
Write-Host "Using Redis container: $redisContainer" -ForegroundColor Cyan
Run-Local "docker exec -i $redisContainer redis-cli LLEN rq:queue:extract" "Failed to query Redis queue length."

Pause-Checkpoint "Confirm job row exists and Redis queue length increased."

# --- Step 6: Start worker and watch logs (optional)
Write-Host "Step 6: Start worker and tail logs (will run in background)" -ForegroundColor Green
Run-DockerCompose "up -d worker" "Failed to start worker via docker compose."
Write-Host "Tailing worker logs in a new window. Close that window to return." -ForegroundColor Cyan
Start-Process -FilePath "powershell" -ArgumentList "-NoProfile","-Command","docker compose logs -f --tail 200 worker" -WindowStyle Normal

Pause-Checkpoint "Watch worker logs. Confirm it picks up the smoke job and updates retrieval_jobs status to completed."

# --- Step 7: Bring API back up and verify health (optional)
Write-Host "Step 7: Bring API back up and verify health" -ForegroundColor Green
Run-DockerCompose "up -d api" "Failed to start api via docker compose."
Start-Sleep -Seconds 3
try {
    $health = Invoke-RestMethod -Uri "$apiHost/healthz" -Method Get -ErrorAction Stop
    Write-Host "API health response:" -ForegroundColor Green
    $health
} catch {
    Write-Host "API health check failed. Inspect API logs." -ForegroundColor Yellow
    Run-DockerCompose "logs --tail 200 api" "Failed to fetch api logs."
}

Write-Host "`nDeployment script finished. If anything looks wrong, follow rollback steps printed below." -ForegroundColor Green

Write-Host "`n=== ROLLBACK / TROUBLESHOOTING ===" -ForegroundColor Yellow
Write-Host "1) Stop API to prevent new jobs: docker compose stop api" -ForegroundColor DarkGray
Write-Host "2) Stop worker: docker compose stop worker" -ForegroundColor DarkGray
Write-Host "3) Revert migration (only after stopping workers): docker compose run --rm api python -m alembic downgrade -1" -ForegroundColor DarkGray
Write-Host "4) Restore DB from backup if needed:" -ForegroundColor DarkGray
Write-Host "   Get-Content .\\backups\\<your_backup>.sql | docker exec -i $pgContainer psql -U postgres" -ForegroundColor DarkGray

# End of script
