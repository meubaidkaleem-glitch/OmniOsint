# Shared helpers for the OmniOSINT Windows scripts. Dot-source this file.
#
# Compatible with Windows PowerShell 5.1 (built into Windows 10 and 11) and
# PowerShell 7. Keep this file ASCII-only: Windows PowerShell 5.1 reads scripts
# without a byte-order mark in the system code page.

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# Pass text to and from Python as UTF-8 (passwords piped on stdin included).
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$script:OmniRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$script:Venv = Join-Path $script:OmniRoot '.venv'
$script:VenvPython = Join-Path $script:Venv 'Scripts\python.exe'
$script:MinPython = [version]'3.12'
$script:MinNode = [version]'22.22.0'
# This file is dot-sourced into the calling script's scope, so a variable set
# here replaces a parameter of the same name. Script variables defined here
# therefore use the Omni prefix (setup.ps1 has a -NonInteractive switch).
$script:OmniNonInteractive = $false

function Write-Step([string]$Message) {
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}
function Write-Info([string]$Message) { Write-Host "    $Message" }
function Write-Good([string]$Message) { Write-Host "    [ok] $Message" -ForegroundColor Green }
function Write-Caution([string]$Message) { Write-Host "    [!]  $Message" -ForegroundColor Yellow }
function Write-Problem([string]$Message) { Write-Host "    [x]  $Message" -ForegroundColor Red }

function Stop-Setup([string]$Message, [string]$Hint = '') {
    # A plain exception marked in .Data (a PowerShell class could not be named
    # by the scripts that dot-source this file).
    $exception = New-Object System.Exception($Message)
    $exception.Data['OmniSetup'] = $true
    $exception.Data['OmniHint'] = $Hint
    throw $exception
}

function Write-SetupFailure($ErrorRecord) {
    $exception = $ErrorRecord.Exception
    Write-Host ''
    if ($exception.Data.Contains('OmniSetup')) {
        Write-Problem $exception.Message
        if ($exception.Data['OmniHint']) { Write-Info $exception.Data['OmniHint'] }
    }
    else {
        Write-Problem "Unexpected error: $($exception.Message)"
        Write-Info ($ErrorRecord.InvocationInfo.PositionMessage -replace "`n", "`n    ")
    }
}

function Get-DataDirectory {
    if ($env:OMNIOSINT_HOME) { return $env:OMNIOSINT_HOME }
    return (Join-Path $env:LOCALAPPDATA 'OmniOSINT')
}

function Update-SessionPath {
    # Pick up PATH changes made by installers without opening a new window.
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ';'
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$What = 'The command'
    )
    # Out-Host matters: without it, the program's output would become part of
    # the return value of whichever function called this one.
    & $FilePath @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Stop-Setup "$What failed (exit code $LASTEXITCODE)." 'See the messages above.'
    }
}

function Get-NativeOutput {
    # Run a program and capture its output without stopping on stderr text.
    # $InputText is deliberately untyped: a [string] parameter turns $null into ''.
    param([string]$FilePath, [string[]]$Arguments = @(), $InputText = $null)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($null -ne $InputText) {
            $lines = $InputText | & $FilePath @Arguments 2>&1 | ForEach-Object { "$_" }
        }
        else {
            $lines = & $FilePath @Arguments 2>&1 | ForEach-Object { "$_" }
        }
        return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = (@($lines) -join "`n") }
    }
    catch {
        return [pscustomobject]@{ ExitCode = -1; Output = $_.Exception.Message }
    }
    finally {
        $ErrorActionPreference = $previous
    }
}

function Read-YesNo([string]$Question, [bool]$Default = $false) {
    if ($script:OmniNonInteractive) { return $Default }
    $suffix = '[y/N]'
    if ($Default) { $suffix = '[Y/n]' }
    while ($true) {
        $answer = Read-Host "    $Question $suffix"
        if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
        $answer = $answer.Trim().ToLowerInvariant()
        if ($answer -eq 'y' -or $answer -eq 'yes') { return $true }
        if ($answer -eq 'n' -or $answer -eq 'no') { return $false }
        Write-Info 'Please answer y or n.'
    }
}

function Read-Choice([string]$Question, [string[]]$Options, [int]$Default = 1) {
    if ($script:OmniNonInteractive) { return $Default }
    Write-Info $Question
    for ($i = 0; $i -lt $Options.Count; $i++) {
        Write-Info ("  [{0}] {1}" -f ($i + 1), $Options[$i])
    }
    while ($true) {
        $answer = Read-Host "    Choice (default $Default)"
        if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
        $number = 0
        if ([int]::TryParse($answer.Trim(), [ref]$number) -and $number -ge 1 -and $number -le $Options.Count) {
            return $number
        }
        Write-Info "Enter a number from 1 to $($Options.Count)."
    }
}

function Read-Value([string]$Prompt, [string]$Default) {
    if ($script:OmniNonInteractive) { return $Default }
    $answer = Read-Host "    $Prompt [$Default]"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer.Trim()
}

function Read-Secret([string]$Prompt) {
    # Never wait for typed input in non-interactive mode: nobody would answer.
    if ($script:OmniNonInteractive) { Stop-Setup "$Prompt is needed, but this run is non-interactive." }
    $secure = Read-Host "    $Prompt" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

function Test-TcpPort([string]$HostName, [int]$Port, [int]$TimeoutMs = 1500) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync($HostName, $Port)
        return ($task.Wait($TimeoutMs) -and $client.Connected)
    }
    catch { return $false }
    finally { $client.Dispose() }
}

function Find-Python([string]$Explicit = '') {
    # Returns the first 64-bit Python 3.12+ found, preferring the tested versions.
    $candidates = New-Object System.Collections.ArrayList
    if ($Explicit) { [void]$candidates.Add(@($Explicit)) }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in @('3.12', '3.13', '3.14')) { [void]$candidates.Add(@($launcher.Source, "-$version")) }
    }
    foreach ($name in @('python.exe', 'python3.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        # The WindowsApps "python.exe" is a shortcut to the Microsoft Store, not Python.
        if ($command -and $command.Source -notlike '*\WindowsApps\*') { [void]$candidates.Add(@($command.Source)) }
    }
    $probe = "import sys,struct;print('%d.%d.%d %d' % (sys.version_info[0], sys.version_info[1], sys.version_info[2], struct.calcsize('P') * 8))"
    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $prefix = @($candidate | Select-Object -Skip 1)
        $result = Get-NativeOutput $exe ($prefix + @('-c', $probe))
        if ($result.ExitCode -ne 0) { continue }
        $parts = $result.Output.Trim().Split(' ')
        if ($parts.Count -ne 2) { continue }
        $version = [version]$parts[0]
        if ($version -ge $script:MinPython -and [int]$parts[1] -eq 64) {
            return [pscustomobject]@{ Exe = $exe; Prefix = $prefix; Version = $version }
        }
    }
    return $null
}

function Find-Node {
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $node) { return $null }
    $result = Get-NativeOutput $node.Source @('--version')
    if ($result.ExitCode -ne 0) { return $null }
    $text = $result.Output.Trim().TrimStart('v')
    try { $version = [version]$text } catch { return $null }
    return [pscustomobject]@{ Exe = $node.Source; Version = $version; Supported = ($version -ge $script:MinNode) }
}

function Find-PostgreSQL {
    $services = @(Get-Service -Name 'postgresql*' -ErrorAction SilentlyContinue)
    $binDir = $null
    $psql = Get-Command psql.exe -ErrorAction SilentlyContinue
    if ($psql) {
        $binDir = Split-Path -Parent $psql.Source
    }
    else {
        $roots = @($env:ProgramFiles, $env:ProgramW6432) | Where-Object { $_ } |
            ForEach-Object { Join-Path $_ 'PostgreSQL' } | Where-Object { Test-Path $_ } | Select-Object -Unique
        $best = $roots | ForEach-Object { Get-ChildItem -Path $_ -Directory } |
            Where-Object { Test-Path (Join-Path $_.FullName 'bin\psql.exe') } |
            Sort-Object { [int](($_.Name -replace '[^0-9].*$', '') + '0') } -Descending |
            Select-Object -First 1
        if ($best) { $binDir = Join-Path $best.FullName 'bin' }
    }
    return [pscustomobject]@{
        Services  = $services
        BinDir    = $binDir
        Listening = (Test-TcpPort '127.0.0.1' 5432)
    }
}

function Install-WithWinget([string]$Id, [string]$Name, [switch]$Interactive, [bool]$Allowed = $false) {
    # Installs software only with the user's explicit consent.
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        Write-Caution "winget is not available, so $Name cannot be installed automatically."
        return $false
    }
    if (-not $Allowed) {
        if ($script:OmniNonInteractive) { return $false }
        if (-not (Read-YesNo "Install $Name now with winget (package $Id)?" $false)) { return $false }
    }
    $arguments = @('install', '--id', $Id, '--exact', '--source', 'winget',
        '--accept-source-agreements', '--accept-package-agreements')
    if ($Interactive) { $arguments += '--interactive' }
    Invoke-Checked $winget.Source $arguments "Installing $Name"
    Update-SessionPath
    return $true
}

function Invoke-Omni {
    # Run the OmniOSINT command line from the project's virtual environment.
    param([string[]]$Arguments, [string]$What = 'OmniOSINT')
    Invoke-Checked $script:VenvPython (@('-m', 'omniosint') + $Arguments) $What
}

function Get-OmniOutput([string[]]$Arguments, $InputText = $null) {
    return Get-NativeOutput $script:VenvPython (@('-m', 'omniosint') + $Arguments) $InputText
}
