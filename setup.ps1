<#
.SYNOPSIS
    Installs or updates OmniOSINT on Windows 10/11 (64-bit).

.DESCRIPTION
    Checks prerequisites, creates the Python virtual environment, installs the
    pinned dependencies, builds the web interface, prepares the database and
    runs the installation diagnostics. Safe to run again: existing settings,
    data and databases are kept.

    Nothing is installed on the system without asking. Missing prerequisites
    can be installed with winget after you confirm, or -InstallMissing allows
    it up front. User data lives outside this folder, in
    %LOCALAPPDATA%\OmniOSINT (or OMNIOSINT_HOME).

.PARAMETER NonInteractive
    Never prompt. Missing prerequisites are reported instead of installed.

.PARAMETER InstallMissing
    Allow installing missing prerequisites (Python, Node.js) with winget.

.PARAMETER Update
    Rebuild the web interface and re-install dependencies even if present.

.PARAMETER SkipFrontend
    Do not build the web interface.

.PARAMETER Database
    How to prepare the database when OmniOSINT cannot reach one yet:
    ask (default), bootstrap (create role and database with a PostgreSQL
    administrator account), existing (use connection details you supply),
    docker (run PostgreSQL in Docker Desktop), skip.

.PARAMETER PostgresAdminUser
    Administrator account used by -Database bootstrap (default: postgres).
    In non-interactive mode its password is read from the environment
    variable OMNIOSINT_PG_ADMIN_PASSWORD.

.PARAMETER PythonPath
    Use this python.exe instead of searching for one.

.EXAMPLE
    .\install.bat
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup.ps1 -NonInteractive -Database bootstrap
#>
[CmdletBinding()]
param(
    [switch]$NonInteractive,
    [switch]$InstallMissing,
    [switch]$Update,
    [switch]$SkipFrontend,
    [ValidateSet('ask', 'bootstrap', 'existing', 'docker', 'skip')]
    [string]$Database = 'ask',
    [string]$PostgresAdminUser = 'postgres',
    [string]$PythonPath = ''
)

. (Join-Path $PSScriptRoot 'scripts\windows\common.ps1')
$script:NonInteractive = [bool]$NonInteractive
$summary = New-Object System.Collections.ArrayList
$exitCode = 0

function Assert-Platform {
    Write-Step 'Checking the platform'
    $os = [Environment]::OSVersion.Version
    if ($os.Major -lt 10 -or -not [Environment]::Is64BitOperatingSystem) {
        Stop-Setup "OmniOSINT needs 64-bit Windows 10 or Windows 11 (found $os)."
    }
    $edition = (Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue).Caption
    if (-not $edition) { $edition = "Windows $($os.Major)" }
    Write-Good "$edition, build $($os.Build), 64-bit"
    $memory = (Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue).TotalPhysicalMemory
    if ($memory -and $memory -lt 4GB) { Write-Caution ('{0:N1} GB of memory; 4 GB or more is recommended.' -f ($memory / 1GB)) }
    $drive = Get-PSDrive -Name ($script:OmniRoot.Substring(0, 1)) -ErrorAction SilentlyContinue
    if ($drive -and $drive.Free -lt 2GB) { Write-Caution ('Only {0:N1} GB free on drive {1}:.' -f ($drive.Free / 1GB), $drive.Name) }
    $wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
    $docker = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($docker) { Write-Info 'Docker found (optional).' } else { Write-Info 'Docker not found (optional).' }
    if ($wsl) { Write-Info 'WSL found (optional).' } else { Write-Info 'WSL not found (optional).' }
}

function Get-Python {
    Write-Step 'Looking for Python 3.12 or later (64-bit)'
    $python = Find-Python $PythonPath
    if (-not $python) {
        Write-Caution 'No suitable Python was found.'
        if (Install-WithWinget 'Python.Python.3.12' 'Python 3.12' -Allowed:$InstallMissing) {
            $python = Find-Python $PythonPath
        }
    }
    if (-not $python) {
        Stop-Setup 'Python 3.12 or later (64-bit) is required.' 'Install it from https://www.python.org/downloads/windows/ (tick "Add python.exe to PATH"), then run install.bat again.'
    }
    Write-Good "Python $($python.Version) ($($python.Exe) $($python.Prefix -join ' '))"
    return $python
}

function Install-PythonEnvironment($python) {
    Write-Step 'Preparing the Python environment'
    if (-not (Test-Path $script:VenvPython)) {
        Invoke-Checked $python.Exe ($python.Prefix + @('-m', 'venv', $script:Venv)) 'Creating the virtual environment'
        Write-Good "Created $script:Venv"
    }
    else {
        Write-Good "Using the existing environment in $script:Venv"
    }
    $pip = @('-m', 'pip', '--disable-pip-version-check', 'install', '--quiet')
    Invoke-Checked $script:VenvPython ($pip + @('--upgrade', 'pip')) 'Updating pip'
    Invoke-Checked $script:VenvPython ($pip + @('--require-hashes', '-r', (Join-Path $script:OmniRoot 'requirements.txt'))) 'Installing the pinned dependencies'
    Invoke-Checked $script:VenvPython ($pip + @('--no-deps', '--editable', $script:OmniRoot)) 'Installing OmniOSINT'
    $version = (Get-OmniOutput @('--version')).Output.Trim()
    Write-Good $version
    [void]$summary.Add("Python environment: $version")
}

function Build-Frontend {
    Write-Step 'Building the web interface'
    $dist = Join-Path $script:OmniRoot 'frontend\dist\index.html'
    if ($SkipFrontend) {
        Write-Caution 'Skipped (-SkipFrontend).'
        return
    }
    if ((Test-Path $dist) -and -not $Update) {
        Write-Good 'Already built. Use -Update to rebuild.'
        return
    }
    $node = Find-Node
    if (-not $node -or -not $node.Supported) {
        if ($node) { Write-Caution "Node.js $($node.Version) is too old; $script:MinNode or later is needed." }
        else { Write-Caution 'Node.js was not found. It is needed only to build the web interface.' }
        if (Install-WithWinget 'OpenJS.NodeJS.LTS' 'Node.js (LTS)' -Allowed:$InstallMissing) { $node = Find-Node }
    }
    if (-not $node -or -not $node.Supported) {
        if (Test-Path $dist) {
            Write-Caution 'Keeping the existing build of the web interface.'
        }
        else {
            Write-Caution 'The web interface was not built. OmniOSINT will run, but the browser shows instructions instead of the interface.'
            Write-Info "Install Node.js $script:MinNode or later from https://nodejs.org/ and run install.bat again."
            [void]$summary.Add('Web interface: NOT BUILT (Node.js missing)')
        }
        return
    }
    $npm = Join-Path (Split-Path -Parent $node.Exe) 'npm.cmd'
    if (-not (Test-Path $npm)) { $npm = 'npm.cmd' }
    Push-Location (Join-Path $script:OmniRoot 'frontend')
    try {
        Invoke-Checked $npm @('ci', '--no-audit', '--no-fund', '--loglevel=error') 'Installing the web interface packages'
        Invoke-Checked $npm @('run', 'build') 'Building the web interface'
    }
    finally { Pop-Location }
    Write-Good "Built with Node.js $($node.Version)"
    [void]$summary.Add('Web interface: built')
}

function Get-DatabaseCheck {
    # Exit codes of "db check": 0 ready, 1 reachable but schema missing or old,
    # 3 invalid configuration, 4 not reachable.
    return Get-OmniOutput @('db', 'check', '--json')
}

function Set-ExistingDatabase {
    Write-Info 'Enter the connection details of an existing PostgreSQL database.'
    $hostName = Read-Value 'Host' '127.0.0.1'
    $port = Read-Value 'Port' '5432'
    $name = Read-Value 'Database name' 'omniosint'
    $user = Read-Value 'User' 'omniosint'
    Invoke-Omni @('config', 'set', 'database.host', $hostName) 'Saving the database host'
    Invoke-Omni @('config', 'set', 'database.port', $port) 'Saving the database port'
    Invoke-Omni @('config', 'set', 'database.name', $name) 'Saving the database name'
    Invoke-Omni @('config', 'set', 'database.user', $user) 'Saving the database user'
    if ($script:NonInteractive) {
        $password = $env:OMNIOSINT_DB_PASSWORD
        if (-not $password) { Stop-Setup 'Set OMNIOSINT_DB_PASSWORD for -Database existing in non-interactive mode.' }
    }
    else {
        $password = Read-Secret "Password for $user"
    }
    $result = Get-OmniOutput @('secrets', 'set', 'database.password', '--stdin') $password
    if ($result.ExitCode -ne 0) { Stop-Setup 'The password could not be stored.' $result.Output }
    Write-Good 'Connection details saved; the password is in the protected secret store.'
}

function Invoke-Bootstrap {
    $pg = Find-PostgreSQL
    if (-not $pg.Listening -and -not $pg.BinDir) {
        Write-Caution 'No PostgreSQL server was found on this computer.'
        Write-Info 'Install PostgreSQL 15 or later (https://www.postgresql.org/download/windows/), remember the'
        Write-Info 'password you choose for the "postgres" account, then run install.bat again.'
        try {
            if (Install-WithWinget 'PostgreSQL.PostgreSQL.16' 'PostgreSQL 16 (its installer will ask you to choose the postgres password)' -Interactive -Allowed:$false) {
                $pg = Find-PostgreSQL
            }
        }
        catch {
            Write-Caution "PostgreSQL was not installed: $($_.Exception.Message)"
        }
    }
    if ($pg.BinDir) { Invoke-Omni @('config', 'set', 'database.pg_bin_dir', $pg.BinDir) 'Saving the PostgreSQL tools folder' }
    if (-not (Test-TcpPort '127.0.0.1' 5432)) {
        $stopped = @($pg.Services | Where-Object { $_.Status -ne 'Running' })
        if ($stopped.Count -gt 0) {
            Write-Caution "The PostgreSQL service $($stopped[0].Name) is not running."
            if (Read-YesNo 'Start it now? (needs administrator rights)' $true) {
                Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -ArgumentList @('-NoProfile', '-Command', "Start-Service -Name '$($stopped[0].Name)'")
            }
        }
    }
    if ($script:NonInteractive) {
        $adminPassword = $env:OMNIOSINT_PG_ADMIN_PASSWORD
        if ($null -eq $adminPassword) { Stop-Setup 'Set OMNIOSINT_PG_ADMIN_PASSWORD for -Database bootstrap in non-interactive mode.' }
    }
    else {
        $adminPassword = Read-Secret "Password of the PostgreSQL account '$PostgresAdminUser'"
    }
    Write-Info 'Creating the OmniOSINT role and database...'
    $result = Get-OmniOutput @('db', 'bootstrap', '--admin-user', $PostgresAdminUser, '--admin-password-stdin') $adminPassword
    Write-Host ($result.Output -replace '(?m)^', '    ')
    if ($result.ExitCode -ne 0) {
        Stop-Setup 'The database could not be created.' 'Check the administrator password and that PostgreSQL is running, or run install.bat again and choose "existing database".'
    }
}

function Start-DockerDatabase {
    $docker = Get-Command docker.exe -ErrorAction SilentlyContinue
    if (-not $docker) { Stop-Setup 'Docker was not found.' 'Install Docker Desktop, or choose another database option.' }
    $envFile = Join-Path $script:OmniRoot '.env.docker'
    if (-not (Test-Path $envFile)) {
        $bytes = New-Object byte[] 24
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $password = [Convert]::ToBase64String($bytes).Replace('+', 'A').Replace('/', 'B').TrimEnd('=')
        Set-Content -Path $envFile -Value "OMNIOSINT_DB_PASSWORD=$password" -Encoding ASCII
    }
    $password = ((Get-Content $envFile | Where-Object { $_ -like 'OMNIOSINT_DB_PASSWORD=*' }) -replace '^OMNIOSINT_DB_PASSWORD=', '').Trim()
    Push-Location $script:OmniRoot
    try {
        Invoke-Checked $docker.Source @('compose', '--env-file', $envFile, 'up', '--detach', '--wait', 'postgres') 'Starting PostgreSQL in Docker'
    }
    finally { Pop-Location }
    Invoke-Omni @('config', 'set', 'database.host', '127.0.0.1') 'Saving the database host'
    Invoke-Omni @('config', 'set', 'database.port', '5433') 'Saving the database port'
    $result = Get-OmniOutput @('secrets', 'set', 'database.password', '--stdin') $password
    if ($result.ExitCode -ne 0) { Stop-Setup 'The database password could not be stored.' $result.Output }
    Write-Good 'PostgreSQL is running in Docker on 127.0.0.1:5433 (data in the volume omniosint-postgres).'
}

function Initialize-Database {
    Write-Step 'Preparing the database'
    $check = Get-DatabaseCheck
    if ($check.ExitCode -eq 3) {
        Stop-Setup 'The configuration is invalid.' 'Run: .venv\Scripts\python.exe -m omniosint config validate'
    }
    if ($check.ExitCode -eq 4) {
        Write-Caution 'OmniOSINT cannot reach a database yet.'
        $mode = $Database
        if ($mode -eq 'ask') {
            $options = @(
                'Create the OmniOSINT database on a PostgreSQL server on this computer (needs the postgres password)',
                'Use an existing PostgreSQL database (enter its connection details)',
                'Run PostgreSQL in Docker Desktop',
                'Skip for now'
            )
            $mode = @('bootstrap', 'existing', 'docker', 'skip')[(Read-Choice 'How should OmniOSINT get its database?' $options 1) - 1]
            if ($script:NonInteractive) { $mode = 'skip' }
        }
        switch ($mode) {
            'bootstrap' { Invoke-Bootstrap }
            'existing' { Set-ExistingDatabase }
            'docker' { Start-DockerDatabase }
            default {
                Write-Caution 'Database not configured. OmniOSINT will not start until it is; run install.bat again when ready.'
                [void]$summary.Add('Database: NOT CONFIGURED')
                return $false
            }
        }
        $check = Get-DatabaseCheck
        if ($check.ExitCode -eq 4) {
            $detail = $check.Output
            try { $detail = ($check.Output | ConvertFrom-Json).detail } catch { }
            Stop-Setup 'The database is still not reachable.' $detail
        }
    }
    Invoke-Omni @('db', 'upgrade') 'Updating the database schema'
    [void]$summary.Add('Database: ready')
    return $true
}

function Show-Diagnostics {
    Write-Step 'Running the installation diagnostics'
    $result = Get-OmniOutput @('doctor')
    Write-Host ($result.Output -replace '(?m)^', '    ')
    if ($result.ExitCode -ne 0) { Write-Caution 'Some checks failed; see above.' }
}

# --------------------------------------------------------------------------- main
$transcript = $null
try {
    $logs = Join-Path (Get-DataDirectory) 'logs'
    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    $transcript = Join-Path $logs ('setup-{0:yyyyMMdd-HHmmss}.log' -f (Get-Date))
    Start-Transcript -Path $transcript -Append | Out-Null
}
catch { $transcript = $null }

try {
    Write-Host 'OmniOSINT setup' -ForegroundColor Cyan
    Write-Info "Program folder: $script:OmniRoot"
    Write-Info "Data folder:    $(Get-DataDirectory)"
    Assert-Platform
    $python = Get-Python
    Install-PythonEnvironment $python
    Build-Frontend
    $databaseReady = Initialize-Database
    Show-Diagnostics
    if (-not $databaseReady) { $exitCode = 2 }

    Write-Step 'Summary'
    foreach ($line in $summary) { Write-Info $line }
    Write-Host ''
    if ($databaseReady) {
        Write-Host '    OmniOSINT is installed. Start it with start.bat' -ForegroundColor Green
        Write-Info 'The first start prints a link that opens first-run setup in your browser.'
    }
}
catch {
    Write-SetupFailure $_
    $exitCode = 1
}
finally {
    if ($transcript) {
        try { Stop-Transcript | Out-Null } catch { }
        Write-Info "A log of this run is in $transcript"
    }
}
exit $exitCode
