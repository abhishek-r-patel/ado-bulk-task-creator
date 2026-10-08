# Azure DevOps Bulk Task Creator: launch CSV task creation in a dedicated Edge session.
# Dependencies are checked locally; pip runs only for missing or incompatible packages.
# The dependency probe uses stdin to preserve Python quotes across PowerShell versions.
# One shared run log records timestamped, source-labelled launcher and Python events.
# Technical diagnostics are file-only; the console shows task progress and actionable results.
# Manual navigation, skipped tags, and profile cleanup are defaults; opt-ins reverse them.
param(
    [string]$PbiUrl,
    [string]$Csv = "tasks.csv",
    [switch]$DryRun,
    [switch]$ValidateOnly,
    [switch]$AutoNavigation,
    [switch]$IncludeTags,
    [switch]$KeepEdgeProfile
)

$ErrorActionPreference = "Stop"
# Derive internal defaults once so Python forwarding and replay logs stay consistent.
$ManualNavigation = -not $AutoNavigation
$SkipTags = -not $IncludeTags
$CleanEdgeProfile = -not $KeepEdgeProfile

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$tempFolder = Join-Path $scriptRoot "temp"
$edgeProfileFolder = Join-Path $tempFolder "SeleniumEdgeProfile"
$logFolder = Join-Path $tempFolder "logs"
$stateFolder = Join-Path $tempFolder "state"

$pythonScript = Join-Path $scriptRoot "create_tasks.py"
$requirementsFile = Join-Path $scriptRoot "requirements.txt"
$runStarted = Get-Date
# PowerShell and Python append to the same file as each stage executes.
$runId = $runStarted.ToString("yyyyMMdd_HHmmss_fffffff")
$runLogFile = Join-Path $logFolder "run_$runId.log"
$scriptExitCode = 1
New-Item -ItemType Directory -Path $logFolder -Force | Out-Null

# Pipeline support captures noninteractive dependency output without printing it to the user.
function Write-RunLog {
    param(
        [Parameter(ValueFromPipeline = $true)][string]$Message,
        [string]$Source = "POWERSHELL",
        [string]$Level = "INFO"
    )
    process {
        $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffzzz"
        foreach ($line in ($Message -split '\r?\n')) {
            Add-Content -LiteralPath $runLogFile -Encoding UTF8 -Value "$timestamp | $Source | $Level | $line"
        }
    }
}

# Record user-facing messages once, then display them without technical log prefixes.
function Write-UserMessage {
    param([string]$Message = "", [ConsoleColor]$ForegroundColor = [ConsoleColor]::Gray)
    if ($Message.Trim()) {
        $level = if ($Message.StartsWith("[ERROR]")) { "ERROR" } elseif ($Message.StartsWith("[WARNING]")) { "WARNING" } else { "INFO" }
        Write-RunLog -Message $Message -Level $level
    }
    Write-Host $Message -ForegroundColor $ForegroundColor
}

try {
if ($PbiUrl) {
    try { $parsedPbiUrl = [uri]$PbiUrl }
    catch { throw "Supply a valid Azure DevOps PBI link." }
    if (-not $parsedPbiUrl.IsAbsoluteUri -or $parsedPbiUrl.UserInfo) {
        throw "Supply an absolute PBI link without embedded credentials."
    }
    # Edit links do not need query/fragment data, which can include authentication tokens.
    $PbiUrl = $parsedPbiUrl.GetLeftPart([System.UriPartial]::Path)
}
$csvFile = if ([System.IO.Path]::IsPathRooted($Csv)) {
    $Csv
}
else {
    Join-Path $scriptRoot $Csv
}

Write-UserMessage ""
Write-UserMessage "============================================" -ForegroundColor Cyan
Write-UserMessage " Azure DevOps Bulk Task Creator" -ForegroundColor Cyan
Write-UserMessage "============================================" -ForegroundColor Cyan
Write-UserMessage ""
Write-RunLog "[RUN] ID: $runId"
Write-RunLog "[RUN] Log file: $runLogFile"
Write-RunLog "[RUN] Started: $($runStarted.ToString('o'))"
Write-RunLog "[RUN] Working directory: $PWD"
Write-RunLog "[RUN] PowerShell: $($PSVersionTable.PSVersion) | Host: $($Host.Name)"
$effectiveParameters = [ordered]@{
    PbiUrl = $PbiUrl
    Csv = $Csv
    ResolvedCsv = $csvFile
    DryRun = [bool]$DryRun
    ValidateOnly = [bool]$ValidateOnly
    AutoNavigation = [bool]$AutoNavigation
    IncludeTags = [bool]$IncludeTags
    KeepEdgeProfile = [bool]$KeepEdgeProfile
    ManualNavigation = [bool]$ManualNavigation
    SkipTags = [bool]$SkipTags
    CleanEdgeProfile = [bool]$CleanEdgeProfile
}
Write-RunLog "[RUN] Supplied parameter names: $($PSBoundParameters.Keys -join ', ')"
Write-RunLog "[RUN] Effective parameters: $($effectiveParameters | ConvertTo-Json -Compress)"
# Double embedded single quotes so recorded paths remain valid PowerShell string literals.
$replayCommand = "& '$($MyInvocation.MyCommand.Path.Replace("'", "''"))' -Csv '$($Csv.Replace("'", "''"))'"
if ($PbiUrl) { $replayCommand += " -PbiUrl '$($PbiUrl.Replace("'", "''"))'" }
foreach ($switchName in @("DryRun", "ValidateOnly", "AutoNavigation", "IncludeTags", "KeepEdgeProfile")) {
    if ($effectiveParameters[$switchName]) { $replayCommand += " -$switchName" }
}
Write-RunLog "[RUN] Replay command (URL query/fragment omitted): $replayCommand"
Write-RunLog "[RUN] PBI URL query/fragment omitted. Logs contain work-item information; review before sharing."

# ------------------------------------------------------------
# Create required folders
# ------------------------------------------------------------

$requiredFolders = @(
    $tempFolder,
    $edgeProfileFolder,
    $logFolder,
    $stateFolder
)

Write-RunLog "[STEP 1] Prepare runtime folders"
foreach ($folder in $requiredFolders) {
    if (-not (Test-Path $folder)) {
        New-Item -ItemType Directory -Path $folder -Force | Out-Null
        Write-RunLog "[CREATED] $folder"
    }
    else {
        Write-RunLog "[EXISTS] $folder"
    }
}

# ------------------------------------------------------------
# Validate required files
# ------------------------------------------------------------

$requiredFiles = @(
    $pythonScript,
    $requirementsFile,
    $csvFile
)

Write-RunLog "[STEP 2] Validate input and source files"
foreach ($file in $requiredFiles) {
    if (-not (Test-Path $file)) {
        Write-UserMessage ""
        Write-UserMessage "[ERROR] Missing required file: $file" -ForegroundColor Red
        exit 1
    }
    # Hashes identify which source/input versions produced a reported result.
    $fileHash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
    Write-RunLog "[FILE] $file | SHA256=$fileHash"
}

# ------------------------------------------------------------
# Find Python
# ------------------------------------------------------------

$pythonCommand = $null

Write-RunLog "[STEP 3] Locate Python"
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCommand = "python"
}
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = "py"
}

if (-not $pythonCommand) {
    Write-UserMessage ""
    Write-UserMessage "[ERROR] Python was not found." -ForegroundColor Red
    Write-UserMessage "Install Python 3 and enable the option to add Python to PATH."
    exit 1
}

$pythonVersion = & $pythonCommand --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Python could not start. Install Python 3 and add it to PATH."
}
Write-RunLog "[OK] $pythonVersion"
Write-RunLog "[RUN] Python command: $pythonCommand | executable: $((Get-Command $pythonCommand).Source)"

# ------------------------------------------------------------
# Install or verify Python dependencies
# ------------------------------------------------------------

# This probe checks local metadata only; it does not contact the package index.
$dependencyCheck = @'
import importlib.util
import sys
from importlib.metadata import version
from pathlib import Path

try:
    from pip._vendor.packaging.requirements import Requirement
    for line in Path(sys.argv[1]).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        installed_version = version(requirement.name)
        print(f"[DEPENDENCY] {requirement.name}={installed_version} | required={requirement.specifier or 'any'}")
        if installed_version not in requirement.specifier:
            sys.exit(1)
    if any(importlib.util.find_spec(name) is None for name in ("selenium", "pandas")):
        sys.exit(1)
except Exception as error:
    print(f"[DEPENDENCY] Local check failed: {type(error).__name__}")
    sys.exit(1)
'@

Write-RunLog "[STEP 4] Check dependencies locally (Python source sent via stdin)"
# stdin preserves Python quotes under both Windows PowerShell and newer argument handling.
$dependencyCheck | & $pythonCommand - $requirementsFile 2>&1 | Write-RunLog -Source DEPENDENCY
$dependencyExitCode = $LASTEXITCODE
Write-RunLog "[STEP 4] Dependency check exit code: $dependencyExitCode"

if ($dependencyExitCode -eq 0) {
    Write-RunLog "[OK] Python dependencies already installed; skipping pip."
}
else {
    Write-UserMessage ""
    Write-UserMessage "Installing missing or incompatible Python dependencies..."
    Write-RunLog "[RUN] Installing from: $requirementsFile | pip options: --no-input --disable-pip-version-check"
    & $pythonCommand -m pip install --no-input --disable-pip-version-check -r $requirementsFile 2>&1 | Write-RunLog -Source PIP
    $installExitCode = $LASTEXITCODE
    Write-RunLog "[STEP 4] Dependency installation exit code: $installExitCode"

    if ($installExitCode -ne 0) {
        Write-UserMessage ""
        Write-UserMessage "[ERROR] Could not install the required Python packages." `
            -ForegroundColor Red
        exit 1
    }

    Write-RunLog "[OK] Python dependencies are available."
}

# ------------------------------------------------------------
# Run the task creator
# ------------------------------------------------------------

Write-UserMessage ""
if (-not $ValidateOnly) {
    if ($ManualNavigation) {
        Write-RunLog "Selenium will open a blank, dedicated Edge window. Paste the PBI link there."
    }
    else {
        Write-RunLog "Selenium will open the PBI in a dedicated Edge window."
    }
    Write-RunLog "Sign in there, including MFA. No PAT is required."
    Write-RunLog "If the sign-in redirect fails, paste the PBI link again in that same window."
    Write-RunLog "Press Enter in the terminal only after the requested PBI loads successfully."
    Write-RunLog "Your usual Edge windows are not used or closed."
    if ($SkipTags) {
        Write-RunLog "CSV tags are omitted for this run; the CSV file is unchanged."
    }
    else {
        Write-RunLog "CSV tags are sent. New tags require Create tag definition permission; omit -IncludeTags to skip tags."
    }
    Write-RunLog "Title, description, and remaining work are sent; area and iteration come from the PBI."
    Write-RunLog "Assigned To uses the CSV AssignedTo value, otherwise the PBI assignee; if both are empty, the task is explicitly unassigned."
    Write-RunLog "Dry run validates without saving; creation requires typing CREATE."
    Write-RunLog "If a request fails, check the PBI before rerunning."
    Write-RunLog "Session cookies are stored under temp/SeleniumEdgeProfile; do not share it."
    if ($CleanEdgeProfile) {
        Write-UserMessage "Browser sign-in data will be deleted after this run." -ForegroundColor Yellow
        Write-RunLog "Logs and the task ledger are retained. Locked profile files are reported, not forcibly removed."
    }
}
Write-UserMessage ""

# An argument array preserves paths with spaces and avoids building an executable command string.
$scriptArguments = @("--csv", $csvFile)
$scriptArguments += @("--run-id", $runId)
$scriptArguments += @("--log-file", $runLogFile)
if ($PbiUrl) { $scriptArguments += @("--pbi-url", $PbiUrl) }
if ($DryRun) { $scriptArguments += "--dry-run" }
if ($ValidateOnly) { $scriptArguments += "--validate-only" }
if ($AutoNavigation) { $scriptArguments += "--auto-navigation" }
if ($IncludeTags) { $scriptArguments += "--include-tags" }
if ($KeepEdgeProfile) { $scriptArguments += "--keep-edge-profile" }

Write-RunLog "[STEP 5] Launch task creator"
Write-RunLog "[RUN] Python script: $pythonScript"
Write-RunLog "[RUN] Python arguments: $(ConvertTo-Json -InputObject $scriptArguments -Compress)"
Push-Location $scriptRoot

try {
    # Do not pipe this interactive process: Python logs directly while prompts stay interactive.
    & $pythonCommand -u $pythonScript @scriptArguments
    $scriptExitCode = $LASTEXITCODE
    Write-RunLog "[STEP 5] Task creator exit code: $scriptExitCode"
}
finally {
    # Restore the user's original working directory even if the task script fails.
    Pop-Location
}

Write-UserMessage ""

if ($scriptExitCode -eq 0) {
    Write-UserMessage `
        "[COMPLETE] Processing finished successfully." `
        -ForegroundColor Green
}
else {
    Write-UserMessage `
        "[WARNING] Processing finished with one or more errors." `
        -ForegroundColor Yellow
}

}
catch {
    $scriptExitCode = 1
    Write-UserMessage "[ERROR] Launcher failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-RunLog "[ERROR] Location: $($_.InvocationInfo.ScriptName):$($_.InvocationInfo.ScriptLineNumber)"
    Write-RunLog "[ERROR] Stack: $($_.ScriptStackTrace)"
}
finally {
    $elapsedSeconds = [math]::Round(((Get-Date) - $runStarted).TotalSeconds, 2)
    Write-RunLog "[RUN END] ID=$runId | exitCode=$scriptExitCode | elapsedSeconds=$elapsedSeconds"
    Write-UserMessage "Logs: $runLogFile"
}

exit $scriptExitCode