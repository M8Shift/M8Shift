# M8Shift local installer for Windows PowerShell / PowerShell.
#
# Intended one-liner from PowerShell:
#   irm https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.ps1 | iex
#
# From cmd.exe:
#   powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.ps1 | iex"
#
# This script installs M8Shift into the current project directory by downloading the
# standalone CLI files, verifying them against checksums.sha256 by default, then
# running `m8shift.py init`. Core install requires only Python 3.8+, Invoke-WebRequest,
# write permission in the target directory, and Get-FileHash (SHA-256). It does not
# modify PATH, does not create a daemon, and needs no package manager. It is kept in
# lockstep with install.sh for the core components (m8shift.py, worktree, runtime,
# context, checksum verification, -NoInit, -Force, -Lang/-Name/-Agents, -DryRun).
#
# Optional helpers (#24): git is only needed for worktree features; the core relay
# installs without it. RTK and Headroom are NEVER installed by this installer (no
# tested native-Windows path, never a silent source build) — use Git Bash or WSL
# with `install.sh --with-rtk` / `--with-headroom` instead. An rtk already on PATH
# is reported honestly and its telemetry is disabled (mirrors install.sh).

[CmdletBinding()]
param(
    [string]$Dir = $(if ($env:M8SHIFT_INSTALL_DIR) { $env:M8SHIFT_INSTALL_DIR } else { (Get-Location).Path }),
    [string]$Agents = "claude,codex",
    [string]$Name = "",
    [string]$Lang = "",
    [switch]$Force,
    [switch]$NoInit,
    [switch]$NoWorktree,
    [switch]$NoRuntime,
    [switch]$NoContext,
    [switch]$DryRun,
    [string]$Ref = $(if ($env:M8SHIFT_INSTALL_REF) { $env:M8SHIFT_INSTALL_REF } else { "main" }),
    [string]$BaseUrl = $(if ($env:M8SHIFT_INSTALL_BASE_URL) { $env:M8SHIFT_INSTALL_BASE_URL } else { "" }),
    [switch]$Verify,
    [switch]$NoVerify,
    [string]$Checksums = $(if ($env:M8SHIFT_INSTALL_CHECKSUMS_URL) { $env:M8SHIFT_INSTALL_CHECKSUMS_URL } else { "" }),
    [string[]]$Sha256 = @(),
    [switch]$Help,
    [switch]$Version
)

$ErrorActionPreference = "Stop"
$InstallerVersion = "1.2.0"
$ChecksumText = ""
$ExpectedSha256 = @{}
# -Checksums given on the command line implies verification (lockstep with
# install.sh --checksums); the env default M8SHIFT_INSTALL_CHECKSUMS_URL does not.
$ChecksumsExplicit = $PSBoundParameters.ContainsKey("Checksums") -and
    -not [string]::IsNullOrWhiteSpace($Checksums)

function Show-Usage {
    @"
M8Shift installer for Windows PowerShell / PowerShell

Usage:
  irm https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.ps1 | iex
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.ps1 | iex"
  .\install.ps1 [options]

Options:
  -Dir DIR             Install into DIR instead of the current directory.
  -Agents A,B          Active roster passed to m8shift.py init (default: claude,codex).
  -Name NAME           Project name passed to m8shift.py init --name.
  -Lang CODE           Language passed to m8shift.py init --lang when bundled.
  -Force               Pass --force to init (reinitialize M8SHIFT.md).
  -NoInit              Download files only; do not run init.
  -NoWorktree          Do not download m8shift-worktree.py.
  -NoRuntime           Do not download m8shift-runtime.py.
  -NoContext           Do not download m8shift-context.py.
  -DryRun              Print the install plan and prerequisites; do not download or write files.
  -Ref REF             Git ref used for downloads when -BaseUrl is not set (default: main).
  -BaseUrl URL         Download base URL (default: GitHub raw for -Ref).
  -Verify              Verify downloaded files against checksums.sha256 (already the default).
  -NoVerify            Skip checksum verification.
  -Checksums URL       Use a custom checksums URL or local path (implies verification).
  -Sha256 FILE:HEX     Pin one expected SHA-256 manually; repeatable.
  -Help                Show this help.
  -Version             Show installer version.

The installer is local-only: no admin rights, no PATH mutation, no background
service, no package manager required. Verification is enabled by default;
-NoVerify disables it, -Verify/-Checksums force it on (overriding
M8SHIFT_INSTALL_VERIFY, like install.sh's explicit flags). install.sh resolves
conflicting verify flags by command-line order (last wins); PowerShell
parameters carry no order, so an explicit -Verify/-Checksums wins over
-NoVerify here (the safe side).
Optional helpers are advisory and never block the core install: git is only
needed for worktree features (m8shift-worktree.py); RTK and Headroom are never
installed by this installer (no tested native-Windows path — use Git Bash or
WSL with install.sh --with-rtk / --with-headroom). An rtk already on PATH is
reported and its telemetry is disabled, mirroring install.sh.
"@
    Show-Prerequisites
}

function Show-Prerequisites {
    @"

Prerequisites:
  core install: Python 3.8+ (stdlib only; python.org, winget install Python.Python.3.12,
    or the Microsoft Store), write permission in the target directory,
    Invoke-WebRequest for downloads, and Get-FileHash for the default SHA-256
    verification (both ship with Windows PowerShell 5.1+ and PowerShell 7+).
  never needed: admin rights, PATH changes, daemons/services, or a package manager
    (winget may provide Python but is never the only path).
  optional git: only worktree features (m8shift-worktree.py) and anchor
    case-renaming use Git; the core relay installs and runs without it.
  optional RTK / Headroom: never installed by install.ps1 (no tested native-Windows
    path); use Git Bash or WSL with install.sh --with-rtk / --with-headroom. An rtk
    already on PATH is detected and its telemetry disabled (mirrors install.sh).
"@
}

function Disable-RtkTelemetry([string]$RtkPath) {
    # Mirrors install.sh's rtk_disable_telemetry: guarded and failure-tolerant —
    # a broken rtk never blocks or fails the core install. Returns $true when
    # telemetry was actually disabled.
    try {
        & $RtkPath telemetry disable *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "OK rtk telemetry disabled"
            return $true
        }
    } catch { }
    Write-Warning "could not disable rtk telemetry; run 'rtk telemetry disable' manually"
    return $false
}

function Show-Capabilities {
    # #24: detect optional-helper capabilities BEFORE any helper setup and report one
    # clear line each (available / unavailable / skipped / installed). install.ps1
    # NEVER installs RTK/Headroom (POSIX-only helpers), but an rtk already on PATH is
    # detected and reported honestly, and its telemetry is disabled (skipped on
    # -DryRun, which must not mutate anything).
    Write-Host "Optional helper capabilities:"
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Host "  git: available - worktree features (m8shift-worktree.py) can use it"
    } else {
        Write-Host "  git: unavailable - worktree features (m8shift-worktree.py) need Git; the core install is unaffected"
    }
    $rtkCmd = Get-Command rtk -ErrorAction SilentlyContinue
    if ($rtkCmd) {
        if ($DryRun) {
            Write-Host "  rtk: available - found at $($rtkCmd.Source); telemetry would be disabled on a real run (install.ps1 never installs RTK - POSIX-only helper)"
        } elseif (Disable-RtkTelemetry $rtkCmd.Source) {
            Write-Host "  rtk: available (telemetry disabled) - found at $($rtkCmd.Source); install.ps1 never installs RTK (POSIX-only helper - use Git Bash/WSL install.sh --with-rtk)"
        } else {
            Write-Host "  rtk: available - found at $($rtkCmd.Source); telemetry could NOT be disabled (run 'rtk telemetry disable' manually)"
        }
    } else {
        Write-Host "  rtk: unavailable - POSIX-only helper, not managed by this installer; use Git Bash/WSL install.sh --with-rtk"
    }
    Write-Host "  headroom: skipped - no tested native-Windows path in install.ps1; use WSL install.sh --with-headroom"
}

function Fail([string]$Message) {
    Write-Error "m8shift install: $Message"
    exit 1
}

function Test-VerifyDefault {
    # Mirrors install.sh's resolver: -Verify and -Checksums are explicit ON
    # signals (--checksums implies verification), -NoVerify is the explicit OFF
    # signal, and any explicit signal overrides M8SHIFT_INSTALL_VERIFY.
    # Caveat: install.sh resolves conflicting explicit flags by command-line
    # order (the last one wins); PowerShell named parameters carry no order, so
    # a -NoVerify + -Verify/-Checksums conflict resolves to the safe side here:
    # verification stays ON.
    if ($Verify -or $ChecksumsExplicit) { return $true }
    if ($NoVerify) { return $false }
    if ($env:M8SHIFT_INSTALL_VERIFY) {
        return $env:M8SHIFT_INSTALL_VERIFY -notin @("0", "false", "False", "FALSE", "no", "No", "NO")
    }
    return $true
}

function Test-SafeRef([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { Fail "unsafe -Ref: $Value" }
    if ($Value.StartsWith("-") -or $Value.Contains("..") -or $Value.Contains("\") -or ($Value -match "\s")) {
        Fail "unsafe -Ref: $Value"
    }
}

function Invoke-DownloadFile([string]$Url, [string]$Destination) {
    $args = @{
        Uri = $Url
        OutFile = $Destination
        ErrorAction = "Stop"
    }
    if ($PSVersionTable.PSVersion.Major -lt 6) {
        $args["UseBasicParsing"] = $true
    }
    Invoke-WebRequest @args
}

function Invoke-DownloadText([string]$Url) {
    $args = @{
        Uri = $Url
        ErrorAction = "Stop"
    }
    if ($PSVersionTable.PSVersion.Major -lt 6) {
        $args["UseBasicParsing"] = $true
    }
    $response = Invoke-WebRequest @args
    return [string]$response.Content
}

function Add-ExpectedSha256([string]$Spec) {
    if ($Spec -match "^([^:=]+)[:=]([0-9a-fA-F]{64})$") {
        $file = $Matches[1]
        $hex = $Matches[2].ToLowerInvariant()
        if ($file -notin @("m8shift.py", "m8shift-worktree.py", "m8shift-runtime.py", "m8shift-context.py")) {
            Fail "-Sha256 file must be m8shift.py, m8shift-worktree.py, m8shift-runtime.py, or m8shift-context.py"
        }
        $script:ExpectedSha256[$file] = $hex
        return
    }
    Fail "-Sha256 expects FILE:HEX"
}

function Add-ManifestSha256([string]$Text) {
    foreach ($line in ($Text -split "`r?`n")) {
        if ($line -match "^\s*([0-9a-fA-F]{64})\s+(\S+)\s*$") {
            $file = $Matches[2]
            if (-not $script:ExpectedSha256.ContainsKey($file)) {
                $script:ExpectedSha256[$file] = $Matches[1].ToLowerInvariant()
            }
        }
    }
}

function Get-ExpectedSha256([string]$Name) {
    if ($script:ExpectedSha256.ContainsKey($Name)) {
        return $script:ExpectedSha256[$Name]
    }
    return ""
}

function Test-DownloadedFile([string]$Name, [string]$Path, [bool]$VerifyDownloads) {
    $expected = Get-ExpectedSha256 $Name
    if ([string]::IsNullOrEmpty($expected)) {
        if ($VerifyDownloads) { Fail "no checksum found for $Name" }
        return
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        Fail "$Name checksum mismatch: expected $expected, got $actual"
    }
    Write-Host "OK verified $Name"
}

function Resolve-Python {
    $candidates = @(
        @{ Exe = "python"; Prefix = @() },
        @{ Exe = "py"; Prefix = @("-3") },
        @{ Exe = "python3"; Prefix = @() }
    )
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) {
            continue
        }
        $prefix = @($candidate.Prefix)
        & $candidate.Exe @prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)" *> $null
        if ($LASTEXITCODE -eq 0) {
            return $candidate
        }
    }
    Fail "Python 3.8+ is required (install from python.org or winget install Python.Python.3.12)"
}

function Invoke-Python([hashtable]$Python, [string[]]$Arguments, [string]$WorkingDirectory) {
    Push-Location $WorkingDirectory
    try {
        $prefix = @($Python.Prefix)
        & $Python.Exe @prefix @Arguments
        if ($LASTEXITCODE -ne 0) {
            Fail "python command failed: $($Arguments -join ' ')"
        }
    } finally {
        Pop-Location
    }
}

function Format-PythonCommand([hashtable]$Python, [string[]]$Arguments) {
    $parts = @($Python.Exe) + @($Python.Prefix) + $Arguments
    return ($parts -join " ")
}

function Install-File([string]$Name, [string]$BaseUrl, [string]$TargetDir, [bool]$VerifyDownloads) {
    # Staged temporary download: fetch to .<name>.tmp.<pid>, verify, then move into
    # place — a failed download or checksum never leaves a half-written target file.
    $url = "$BaseUrl/$Name"
    $dest = Join-Path $TargetDir $Name
    $tmp = Join-Path $TargetDir ".$Name.tmp.$PID"
    if (Test-Path -LiteralPath $tmp) {
        Remove-Item -LiteralPath $tmp -Force
    }
    Write-Host "-> downloading $Name"
    Invoke-DownloadFile $url $tmp
    Test-DownloadedFile $Name $tmp $VerifyDownloads
    Move-Item -LiteralPath $tmp -Destination $dest -Force
}

if ($Help) {
    Show-Usage
    exit 0
}

if ($Version) {
    Write-Host "m8shift install.ps1 $InstallerVersion"
    exit 0
}

$VerifyDownloads = Test-VerifyDefault
Test-SafeRef $Ref

foreach ($spec in $Sha256) {
    Add-ExpectedSha256 $spec
}

if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    $BaseUrl = "https://raw.githubusercontent.com/M8Shift/M8Shift/$Ref"
}
$BaseUrl = $BaseUrl.TrimEnd("/")

if ([string]::IsNullOrWhiteSpace($Checksums)) {
    $Checksums = "$BaseUrl/checksums.sha256"
}

if ($DryRun) {
    # Plan only: no directory creation, no download, no write, no init.
    Show-Prerequisites
    Write-Host ""
    Show-Capabilities
    Write-Host ""
    Write-Host "Dry run plan:"
    Write-Host "  target: $Dir"
    Write-Host "  ref: $Ref"
    Write-Host "  base URL: $BaseUrl"
    Write-Host "  checksums: $Checksums"
    Write-Host "  agents: $Agents"
    Write-Host "  verify downloads: $VerifyDownloads"
    Write-Host "  download worktree/runtime/context: $(-not $NoWorktree)/$(-not $NoRuntime)/$(-not $NoContext)"
    Write-Host "  run init: $(-not $NoInit)"
    Write-Host "  RTK/Headroom: never installed by install.ps1 (POSIX-only helpers; use Git Bash/WSL install.sh --with-rtk / --with-headroom)"
    Write-Host ""
    Write-Host "No files were downloaded or written."
    exit 0
}

New-Item -ItemType Directory -Force -Path $Dir | Out-Null
$TargetDir = (Resolve-Path -LiteralPath $Dir).Path
Show-Prerequisites
Show-Capabilities

if ($VerifyDownloads) {
    if (Test-Path -LiteralPath $Checksums) {
        Write-Host "-> reading checksums"
        $ChecksumText = Get-Content -LiteralPath $Checksums -Raw
    } else {
        Write-Host "-> downloading checksums"
        $ChecksumText = Invoke-DownloadText $Checksums
    }
    Add-ManifestSha256 $ChecksumText
}

$Python = Resolve-Python

Install-File "m8shift.py" $BaseUrl $TargetDir $VerifyDownloads
if (-not $NoWorktree) {
    Install-File "m8shift-worktree.py" $BaseUrl $TargetDir $VerifyDownloads
}
if (-not $NoRuntime) {
    Install-File "m8shift-runtime.py" $BaseUrl $TargetDir $VerifyDownloads
}
if (-not $NoContext) {
    Install-File "m8shift-context.py" $BaseUrl $TargetDir $VerifyDownloads
}

if (-not $NoInit) {
    $initArgs = @(".\m8shift.py", "init", "--agents", $Agents)
    if (-not [string]::IsNullOrEmpty($Name)) {
        $initArgs += @("--name", $Name)
    }
    if (-not [string]::IsNullOrEmpty($Lang)) {
        $initArgs += @("--lang", $Lang)
    }
    if ($Force) {
        $initArgs += "--force"
    }
    Write-Host "-> initializing M8Shift in $TargetDir"
    Invoke-Python $Python $initArgs $TargetDir
}

$firstAgent = ($Agents -split ",")[0]
Write-Host ""
Write-Host "OK M8Shift installed in $TargetDir"
Write-Host ""
Write-Host "Next:"
Write-Host "  cd `"$TargetDir`""
Write-Host "  $(Format-PythonCommand $Python @("m8shift.py", "status"))"
Write-Host "  $(Format-PythonCommand $Python @("m8shift.py", "next", $firstAgent))"
