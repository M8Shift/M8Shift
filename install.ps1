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
# running `m8shift.py init`. It does not modify PATH and does not create a daemon.

[CmdletBinding()]
param(
    [string]$Dir = $(if ($env:M8SHIFT_INSTALL_DIR) { $env:M8SHIFT_INSTALL_DIR } else { (Get-Location).Path }),
    [string]$Agents = "claude,codex",
    [string]$Name = "",
    [string]$Lang = "",
    [switch]$Force,
    [switch]$NoInit,
    [switch]$NoWorktree,
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
$InstallerVersion = "1.0.0"
$ChecksumText = ""
$ExpectedSha256 = @{}

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
  -Ref REF             Git ref used for downloads when -BaseUrl is not set (default: main).
  -BaseUrl URL         Download base URL (default: GitHub raw for -Ref).
  -Verify              Verify downloaded files against checksums.sha256.
  -NoVerify            Skip checksum verification.
  -Checksums URL       Use a custom checksums URL or local path.
  -Sha256 FILE:HEX     Pin one expected SHA-256 manually; repeatable.
  -Help                Show this help.
  -Version             Show installer version.

Verification is enabled by default. -NoVerify disables it.
"@
}

function Fail([string]$Message) {
    Write-Error "m8shift install: $Message"
    exit 1
}

function Test-VerifyDefault {
    if ($NoVerify) { return $false }
    if ($Verify) { return $true }
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
        if ($file -notin @("m8shift.py", "m8shift-worktree.py")) {
            Fail "-Sha256 file must be m8shift.py or m8shift-worktree.py"
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

New-Item -ItemType Directory -Force -Path $Dir | Out-Null
$TargetDir = (Resolve-Path -LiteralPath $Dir).Path

if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    $BaseUrl = "https://raw.githubusercontent.com/M8Shift/M8Shift/$Ref"
}
$BaseUrl = $BaseUrl.TrimEnd("/")

if ([string]::IsNullOrWhiteSpace($Checksums)) {
    $Checksums = "$BaseUrl/checksums.sha256"
}

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
