param(
    [ValidateSet("start", "debug", "scan", "dependencies")]
    [string]$Mode = "start"
)

$ErrorActionPreference = "Stop"
$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $env:LOCALAPPDATA "ProjectAtlasTracker\logs"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$Session = Get-Date -Format "yyyyMMddHHmmss"
$LogFile = Join-Path $LogDir ("atlas_launcher_{0}.log" -f $Session)

function Write-AtlasLog([string]$Text) {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss.fff"), $Text
    $line | Tee-Object -FilePath $LogFile -Append
}

Write-AtlasLog "Project Atlas Tracker launcher"
Write-AtlasLog ("Mode: {0}" -f $Mode)
Write-AtlasLog ("Program folder: {0}" -f $AppDir)

$candidates = @(
    @{ Exe = "py"; Args = @("-3.14") },
    @{ Exe = "py"; Args = @("-3.13") },
    @{ Exe = "py"; Args = @("-3.12") },
    @{ Exe = "py"; Args = @("-3.11") },
    @{ Exe = "python"; Args = @() }
)

$PythonExe = $null
$PythonPrefix = @()
foreach ($candidate in $candidates) {
    $command = Get-Command $candidate.Exe -ErrorAction SilentlyContinue
    if ($null -eq $command) { continue }
    try {
        & $candidate.Exe @($candidate.Args) -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
        if ($LASTEXITCODE -eq 0) {
            $PythonExe = $candidate.Exe
            $PythonPrefix = @($candidate.Args)
            break
        }
    } catch { continue }
}

if ($null -eq $PythonExe) {
    Write-AtlasLog "ERROR: Python 3.11 or newer was not found."
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("Python 3.11 or newer was not found.", "Project Atlas Tracker", "OK", "Error") | Out-Null
    exit 1
}

$ActualPython = (& $PythonExe @PythonPrefix -c "import sys; print(sys.executable)").Trim()
$VersionText = & $PythonExe @PythonPrefix -c "import sys; print(sys.version.split()[0])"
Write-AtlasLog ("Python: {0} ({1})" -f $ActualPython, $VersionText)
$Requirements = Join-Path $AppDir "requirements-media.txt"
try {
    & $ActualPython -c "import PIL, openpyxl" *> $null
    $DependenciesReady = ($LASTEXITCODE -eq 0)
} catch { $DependenciesReady = $false }
if (-not $DependenciesReady -and $Mode -eq "dependencies") {
    Write-AtlasLog "Installing optional media dependencies (Pillow, openpyxl)."
    $PipStdout = Join-Path $LogDir ("atlas_pip_{0}.out.log" -f $Session)
    $PipStderr = Join-Path $LogDir ("atlas_pip_{0}.err.log" -f $Session)
    try {
        $PipArguments = @("-m", "pip", "install", "--user", "--disable-pip-version-check", "--only-binary=:all:", "--progress-bar", "off", "-r", "`"$Requirements`"")
        $PipProcess = Start-Process -FilePath $ActualPython -ArgumentList $PipArguments -NoNewWindow -Wait -PassThru -RedirectStandardOutput $PipStdout -RedirectStandardError $PipStderr
        foreach ($line in @(Get-Content -Path $PipStdout -ErrorAction SilentlyContinue)) { Write-AtlasLog $line }
        foreach ($line in @(Get-Content -Path $PipStderr -ErrorAction SilentlyContinue)) { Write-AtlasLog ("pip: {0}" -f $line) }
        $DependenciesReady = ($PipProcess.ExitCode -eq 0)
    } catch {
        Write-AtlasLog ("WARNING: Optional dependency installation failed: {0}" -f $_.Exception.Message)
        $DependenciesReady = $false
    } finally {
        Remove-Item -LiteralPath $PipStdout, $PipStderr -Force -ErrorAction SilentlyContinue
    }
} elseif (-not $DependenciesReady) {
    Write-AtlasLog "Optional media dependencies are missing; normal launch will continue without them."
}
if ($Mode -eq "dependencies") {
    if ($DependenciesReady) { Write-AtlasLog "Optional media dependencies are ready."; exit 0 }
    Write-AtlasLog "ERROR: Optional media dependencies could not be installed."; exit 1
}
if (-not $DependenciesReady) {
    Write-AtlasLog "WARNING: Tracker is starting without DDS/WebP and Main DB processing."
}
$RunPath = Join-Path $AppDir "run.py"

if ($Mode -eq "scan") {
    Set-Location $AppDir
    & $ActualPython $RunPath --scan 2>&1 | Tee-Object -FilePath $LogFile -Append
    exit $LASTEXITCODE
}

if ($Mode -eq "debug") {
    Set-Location $AppDir
    & $ActualPython $RunPath --no-browser 2>&1 | Tee-Object -FilePath $LogFile -Append
    exit $LASTEXITCODE
}

$ErrorLog = Join-Path $LogDir ("atlas_runtime_{0}.err.log" -f $Session)
$OutputLog = Join-Path $LogDir ("atlas_runtime_{0}.out.log" -f $Session)
$process = Start-Process -FilePath $ActualPython -ArgumentList @("`"$RunPath`"", "--desktop") -WorkingDirectory $AppDir -WindowStyle Hidden -RedirectStandardOutput $OutputLog -RedirectStandardError $ErrorLog -PassThru
Write-AtlasLog ("Started hidden process PID {0}" -f $process.Id)
Start-Sleep -Milliseconds 900
if ($process.HasExited -and $process.ExitCode -ne 0) {
    Write-AtlasLog ("ERROR: Process ended with code {0}" -f $process.ExitCode)
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("Project Atlas Tracker could not be started.`n`nLog: $ErrorLog", "Project Atlas Tracker", "OK", "Error") | Out-Null
    exit $process.ExitCode
}
exit 0
