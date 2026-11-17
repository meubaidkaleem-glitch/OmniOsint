<#
.SYNOPSIS
    Removes what install.bat created in this folder.

.DESCRIPTION
    Removes the Python environment (.venv), the web interface build and its
    packages, and the desktop shell build output. Keeps, unless you explicitly
    choose otherwise:

      - your data folder (settings, secret store, logs, backups),
      - the PostgreSQL database and anything else on the database server,
      - Python, Node.js, PostgreSQL and other programs you installed.

    Delete this folder afterwards to remove the program files themselves.
#>
[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$RemoveData
)

. (Join-Path $PSScriptRoot 'common.ps1')
$script:NonInteractive = [bool]$Yes
$exitCode = 0

try {
    $dataDir = Get-DataDirectory
    $targets = @(
        $script:Venv,
        (Join-Path $script:OmniRoot 'frontend\node_modules'),
        (Join-Path $script:OmniRoot 'frontend\dist'),
        (Join-Path $script:OmniRoot 'desktop\node_modules'),
        (Join-Path $script:OmniRoot 'desktop\src-tauri\target')
    ) | Where-Object { Test-Path $_ }

    Write-Host 'OmniOSINT uninstall' -ForegroundColor Cyan
    if (Test-Path $script:VenvPython) {
        Write-Step 'Stopping OmniOSINT'
        $stop = Get-OmniOutput @('stop')
        Write-Host ($stop.Output -replace '(?m)^', '    ')
    }

    Write-Step 'This removes'
    if ($targets) { foreach ($target in $targets) { Write-Info $target } } else { Write-Info '(nothing: already removed)' }
    Write-Step 'This keeps'
    Write-Info "Your data folder: $dataDir"
    Write-Info 'The PostgreSQL database, and the programs you installed (Python, Node.js, PostgreSQL)'

    if ($targets -and -not $Yes) {
        if (-not (Read-YesNo 'Remove the listed folders?' $false)) { Stop-Setup 'Nothing was removed.' }
    }
    foreach ($target in $targets) {
        Remove-Item -LiteralPath $target -Recurse -Force
        Write-Good "Removed $target"
    }

    if (Test-Path $dataDir) {
        $deleteData = $false
        if ($RemoveData) {
            $deleteData = $true
        }
        elseif (-not $Yes) {
            Write-Host ''
            Write-Caution "Your data folder contains settings, the secret store, logs and BACKUPS: $dataDir"
            $answer = Read-Host '    To delete it permanently type DELETE, or press Enter to keep it'
            $deleteData = ($answer -ceq 'DELETE')
        }
        if ($deleteData) {
            Remove-Item -LiteralPath $dataDir -Recurse -Force
            Write-Good "Deleted $dataDir"
        }
        else {
            Write-Good "Kept $dataDir"
        }
    }

    Write-Step 'The database'
    Write-Info 'The database was not touched. To remove it, an administrator can run in psql:'
    Write-Info '    DROP DATABASE omniosint;  DROP ROLE omniosint;'
    Write-Info 'If you used the Docker option:  docker compose down --volumes'
}
catch {
    Write-SetupFailure $_
    $exitCode = 1
}
exit $exitCode
