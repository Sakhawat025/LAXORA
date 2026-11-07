param(
    [Parameter(Mandatory=$true)][string]$ExistingProject
)
$ErrorActionPreference = 'Stop'
$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$targetRoot = (Resolve-Path $ExistingProject).Path
if ($sourceRoot -eq $targetRoot) { throw 'Extract the new ZIP to a separate folder, then point -ExistingProject at your original running project.' }
if (!(Test-Path (Join-Path $targetRoot 'compose.yaml')) -or !(Test-Path (Join-Path $targetRoot '.env'))) {
    throw 'ExistingProject must be the original laxora folder containing compose.yaml and .env.'
}
Get-Command docker -ErrorAction Stop | Out-Null
Get-Command python -ErrorAction Stop | Out-Null
Push-Location $targetRoot
$webStopped = $false
try {
    Write-Host 'Checking the existing services...'
    $running = @(docker compose ps --services --status running)
    if ($LASTEXITCODE -ne 0 -or $running -notcontains 'db' -or $running -notcontains 'api') {
        throw 'Start the original project first: docker compose up -d. Then retry this update.'
    }
    Write-Host 'Temporarily stopping the web interface and taking a backup...'
    docker compose stop web
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop web interface.' }
    $webStopped = $true
    python scripts/backup.py
    if ($LASTEXITCODE -ne 0) { throw 'Backup failed. Project files have not been replaced.' }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $codeBackup = Join-Path $targetRoot "backups/source-$stamp"
    New-Item -ItemType Directory -Path $codeBackup -Force | Out-Null
    foreach ($entry in @('backend','frontend','scripts','docs','compose.yaml','README.md')) {
        $original=Join-Path $targetRoot $entry
        if(Test-Path $original) {
            if((Get-Item $original).PSIsContainer) {
                robocopy $original (Join-Path $codeBackup $entry) /E /XD node_modules .next __pycache__ .pytest_cache uploads .venv /XF '*.pyc' '*.tsbuildinfo' '.env' '.env.local' /NFL /NDL /NJH /NJS | Out-Null
                if($LASTEXITCODE -ge 8){ throw 'Could not back up source files.' }
            } else { Copy-Item -LiteralPath $original -Destination $codeBackup -Force }
        }
    }
    Write-Host 'Copying updated source. Existing .env, database volumes and uploads are preserved...'
    robocopy $sourceRoot $targetRoot /E /XD node_modules .next .git .venv __pycache__ .pytest_cache backups uploads /XF '.env' '.env.local' '*.pyc' '*.tsbuildinfo' '*.db' /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -ge 8) { throw 'Source update failed. The previous source is available in backups.' }
    docker compose up --build -d
    if ($LASTEXITCODE -ne 0) { throw 'Build or startup failed. Read docker compose logs api web. The backup has been preserved.' }
    $webStopped=$false
    Write-Host 'Update complete. Open http://localhost:3000 . Your existing accounts and passwords are unchanged.'
} finally {
    if($webStopped){Write-Host 'If the web interface remains stopped, inspect the output and run docker compose up -d after resolving the error.'}
    Pop-Location
}
