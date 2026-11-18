<#
.SYNOPSIS
    Updates OmniOSINT in place and keeps all user data.

.DESCRIPTION
    1. Stops OmniOSINT if it is running.
    2. Backs up the database (unless -SkipBackup).
    3. Fetches the new version with git, when this folder is a git checkout.
    4. Re-runs setup.ps1 -Update: dependencies, web interface, schema upgrade.
    5. Starts OmniOSINT again if it was running.

    User data (settings, secrets, logs, backups) lives outside this folder and
    is never modified, and the database is only changed by schema migrations.
#>
[CmdletBinding()]
param(
    [switch]$NonInteractive,
    [switch]$SkipBackup,
    [switch]$NoPull
)

. (Join-Path $PSScriptRoot 'common.ps1')
$script:OmniNonInteractive = [bool]$NonInteractive
$exitCode = 0

try {
    if (-not (Test-Path $script:VenvPython)) {
        Stop-Setup 'OmniOSINT is not installed in this folder.' 'Run install.bat first.'
    }

    Write-Step 'Stopping OmniOSINT'
    $status = Get-OmniOutput @('status', '--json')
    $wasRunning = $false
    if ($status.ExitCode -eq 0) {
        try { $wasRunning = [bool](($status.Output | ConvertFrom-Json).running) } catch { $wasRunning = $false }
    }
    if ($wasRunning) { Invoke-Omni @('stop') 'Stopping OmniOSINT' } else { Write-Good 'Not running.' }

    if (-not $SkipBackup) {
        Write-Step 'Backing up the database'
        $backup = Get-OmniOutput @('backup', 'create', '--label', 'pre-update')
        Write-Host ($backup.Output -replace '(?m)^', '    ')
        if ($backup.ExitCode -ne 0) {
            Write-Caution 'The backup could not be made.'
            if (-not (Read-YesNo 'Continue the update without a backup?' $false)) {
                Stop-Setup 'Update cancelled; nothing was changed.'
            }
        }
    }

    if (-not $NoPull) {
        Write-Step 'Fetching the new version'
        $git = Get-Command git.exe -ErrorAction SilentlyContinue
        if ((Test-Path (Join-Path $script:OmniRoot '.git')) -and $git) {
            $changes = Get-NativeOutput $git.Source @('-C', $script:OmniRoot, 'status', '--porcelain', '--untracked-files=no')
            if ($changes.Output.Trim()) {
                Write-Caution 'This folder has local changes, so it was not updated automatically:'
                Write-Host ($changes.Output -replace '(?m)^', '      ')
                Stop-Setup 'Update cancelled.' 'Commit or undo the changes, then run update.bat again (or use -NoPull).'
            }
            Invoke-Checked $git.Source @('-C', $script:OmniRoot, 'pull', '--ff-only') 'Fetching the update'
        }
        else {
            Write-Caution 'This folder is not a git checkout, so the new version cannot be fetched automatically.'
            Write-Info 'Extract the new release over this folder (your data is stored separately), then run update.bat -NoPull.'
            Stop-Setup 'Nothing was downloaded.'
        }
    }

    Write-Step 'Updating the installation'
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $script:OmniRoot 'setup.ps1'), '-Update')
    if ($NonInteractive) { $arguments += '-NonInteractive' }
    & powershell.exe @arguments
    if ($LASTEXITCODE -ne 0) { Stop-Setup "Setup reported a problem (exit code $LASTEXITCODE)." 'See its messages above. Your previous data is in the pre-update backup.' }

    if ($wasRunning) {
        Write-Step 'Starting OmniOSINT again'
        Invoke-Omni @('start') 'Starting OmniOSINT'
    }
    Write-Host ''
    Write-Host '    Update complete.' -ForegroundColor Green
}
catch {
    Write-SetupFailure $_
    $exitCode = 1
}
exit $exitCode
