<#
.SYNOPSIS
    One-shot scaffold for the mc34b-6p3s-mod repository.
.DESCRIPTION
    - Creates the standard folder tree (models / simulations / docs / tools).
    - Moves SPICE files already sitting in the root into place and rewrites
      their ".include xxx.inc" lines to point at ../../models/.
    - Drops .gitkeep into empty folders so Git tracks them.
    - Runs "git init" on branch "main" if Git is installed and no repo exists.
    Idempotent: safe to run again, never overwrites an existing file.
.EXAMPLE
    # put this script in the project root, then:
    powershell -ExecutionPolicy Bypass -File .\setup-repo.ps1
#>
[CmdletBinding()]
param(
    [string]$Root = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrEmpty($Root)) { $Root = (Get-Location).Path }
Set-Location -LiteralPath $Root
Write-Host "Project root: $Root" -ForegroundColor Cyan

# ---------------------------------------------------------------- folders
$dirs = @(
    'models',                 # SPICE .inc / .lib / .asy
    'simulations\ltspice',    # .cir / .asc
    'simulations\psud2',      # .psu
    'docs\datasheets',        # tube datasheets used to fit / check models
    'docs\figures',           # simulation plots (tools/make_figures.py)
    'tools'                   # helper scripts
)
foreach ($d in $dirs) {
    $p = Join-Path $Root $d
    if (-not (Test-Path -LiteralPath $p)) {
        New-Item -ItemType Directory -Path $p | Out-Null
        Write-Host "  [+] $d"
    }
}

# ---------------------------------------------------------------- helpers
function Move-IfAbsent {
    param([System.IO.FileInfo]$File, [string]$DestDir)
    $dest = Join-Path (Join-Path $Root $DestDir) $File.Name
    if (Test-Path -LiteralPath $dest) {
        Write-Warning "skip, already exists: $DestDir\$($File.Name)"
        return $null
    }
    Move-Item -LiteralPath $File.FullName -Destination $dest
    Write-Host "  [>] $($File.Name) -> $DestDir"
    return $dest
}

$rootFiles = Get-ChildItem -LiteralPath $Root -File

# ---------------------------------------------------------------- models
$rootFiles | Where-Object { $_.Extension -in '.inc', '.lib', '.sub', '.asy' } |
    ForEach-Object { [void](Move-IfAbsent $_ 'models') }

# ------------------------------------------------- LTspice netlists/schematics
$moved = @()
$rootFiles | Where-Object { $_.Extension -in '.cir', '.asc', '.sp' } |
    ForEach-Object {
        $m = Move-IfAbsent $_ 'simulations\ltspice'
        if ($m) { $moved += $m }
    }

# rewrite bare ".include foo.inc" -> ".include ../../models/foo.inc"
$pattern = '(?im)^(\s*\.(?:include|inc|lib)\s+)(?!\S*[\\/])(\S+\.(?:inc|lib|sub))'
foreach ($f in $moved) {
    $txt = [System.IO.File]::ReadAllText($f)
    $new = [regex]::Replace($txt, $pattern, '${1}../../models/${2}')
    if ($new -ne $txt) {
        [System.IO.File]::WriteAllText($f, $new)
        Write-Host "  [~] include path fixed: $(Split-Path $f -Leaf)"
    }
}

# ---------------------------------------------------------------- PSUD2 / docs
$rootFiles | Where-Object { $_.Extension -eq '.psu' } |
    ForEach-Object { [void](Move-IfAbsent $_ 'simulations\psud2') }
$rootFiles | Where-Object { $_.Extension -eq '.pdf' } |
    ForEach-Object { [void](Move-IfAbsent $_ 'docs\datasheets') }

# ---------------------------------------------------------------- .gitkeep
foreach ($d in $dirs) {
    $p = Join-Path $Root $d
    if (-not (Get-ChildItem -LiteralPath $p -Force | Select-Object -First 1)) {
        New-Item -ItemType File -Path (Join-Path $p '.gitkeep') | Out-Null
    }
}

# ---------------------------------------------------------------- git
if (Get-Command git -ErrorAction SilentlyContinue) {
    if (-not (Test-Path -LiteralPath (Join-Path $Root '.git'))) {
        git init --quiet
        git symbolic-ref HEAD refs/heads/main
        Write-Host "  [git] initialised on branch main" -ForegroundColor Green
    } else {
        Write-Host "  [git] repository already exists, left untouched"
    }
} else {
    Write-Warning "Git not found - install Git for Windows, then run: git init -b main"
}

Write-Host "`nDone. Next:" -ForegroundColor Cyan
Write-Host "  git add ."
Write-Host "  git commit -m `"chore: scaffold repo, models v2, channel sim v1`""
