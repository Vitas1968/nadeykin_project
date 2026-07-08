param(
    [string]$OutDir
)

$ErrorActionPreference = "Stop"
$StageDir = $null
$Failed = $false

try {
    $ScriptDir = $PSScriptRoot
    if ([string]::IsNullOrWhiteSpace($ScriptDir)) {
        $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    }

    $RepoRoot = Split-Path -Parent $ScriptDir
    $SkillDir = Join-Path $RepoRoot "tender-assistant-skill"
    if ([string]::IsNullOrWhiteSpace($OutDir)) {
        if ([string]::IsNullOrWhiteSpace($env:SKILL_OUT_DIR)) {
            $OutDir = Join-Path ([System.IO.Path]::GetTempPath()) "skill_zip_test"
        }
        else {
            $OutDir = $env:SKILL_OUT_DIR
        }
    }

    $ResolvedOutDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutDir)
    $ZipPath = Join-Path $ResolvedOutDir "tender-assistant-skill.zip"
    $StageDir = Join-Path ([System.IO.Path]::GetTempPath()) ("tender-assistant-skill-stage-" + [System.Guid]::NewGuid().ToString("N"))

    if (-not (Test-Path $SkillDir)) {
        throw "Skill directory not found: $SkillDir"
    }

    if (-not (Test-Path (Join-Path $SkillDir "SKILL.md"))) {
        throw "SKILL.md not found in skill directory."
    }

    if (-not (Test-Path (Join-Path $SkillDir "run.py"))) {
        throw "run.py not found in skill directory."
    }

    # These folders are QA workspace placeholders; build staging stays in temp.
    New-Item -ItemType Directory -Force $ResolvedOutDir | Out-Null
    New-Item -ItemType Directory -Force (Join-Path $ResolvedOutDir "input") | Out-Null
    New-Item -ItemType Directory -Force (Join-Path $ResolvedOutDir "out") | Out-Null
    New-Item -ItemType Directory -Force (Join-Path $ResolvedOutDir "skill") | Out-Null

    Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force $StageDir | Out-Null

    $RequiredFiles = @(
        "SKILL.md",
        "AGENT_PROMPT.md",
        "requirements.txt",
        ".env.example",
        "run.py"
    )

    foreach ($File in $RequiredFiles) {
        $Source = Join-Path $SkillDir $File
        if (-not (Test-Path $Source)) {
            throw "Required file missing: $Source"
        }
        Copy-Item $Source (Join-Path $StageDir $File) -Force
    }

    $DirsToCopy = @(
        "config",
        "prompts",
        "src",
        "docs"
    )

    foreach ($Dir in $DirsToCopy) {
        $Source = Join-Path $SkillDir $Dir
        if (-not (Test-Path $Source)) {
            throw "Required directory missing: $Source"
        }
        Copy-Item $Source (Join-Path $StageDir $Dir) -Recurse -Force
    }

    $RepoReadme = Join-Path $RepoRoot "README.md"
    if (Test-Path $RepoReadme) {
        Copy-Item $RepoReadme (Join-Path $StageDir "README.md") -Force
    }

    Get-ChildItem $StageDir -Directory -Recurse -Force -Filter "__pycache__" | Remove-Item -Recurse -Force
    Get-ChildItem $StageDir -Directory -Recurse -Force -Filter ".pytest_cache" | Remove-Item -Recurse -Force
    Get-ChildItem $StageDir -Directory -Recurse -Force -Filter ".mypy_cache" | Remove-Item -Recurse -Force
    Get-ChildItem $StageDir -Directory -Recurse -Force -Filter ".ruff_cache" | Remove-Item -Recurse -Force
    Get-ChildItem $StageDir -File -Recurse -Force -Include *.pyc,*.pyo | Remove-Item -Force

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $ZipArchive = $null
    $ZipArchive = [System.IO.Compression.ZipFile]::Open($ZipPath, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        Get-ChildItem -LiteralPath $StageDir -File -Recurse -Force | ForEach-Object {
            $RelativePath = $_.FullName.Substring($StageDir.Length).TrimStart(
                [System.IO.Path]::DirectorySeparatorChar,
                [System.IO.Path]::AltDirectorySeparatorChar
            )
            $EntryName = $RelativePath.Replace([System.IO.Path]::DirectorySeparatorChar, "/").Replace([System.IO.Path]::AltDirectorySeparatorChar, "/")
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($ZipArchive, $_.FullName, $EntryName, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
        }
    }
    finally {
        if ($null -ne $ZipArchive) {
            $ZipArchive.Dispose()
        }
    }

    Write-Host "Skill zip created: $ZipPath"
    Write-Host "Zip root contains SKILL.md, run.py, requirements.txt, AGENT_PROMPT.md, config/, prompts/, src/, docs/."
}
catch {
    Write-Error -Message $_.Exception.Message -ErrorAction Continue
    $Failed = $true
}
finally {
    if ($null -ne $StageDir -and (Test-Path $StageDir)) {
        Remove-Item -Recurse -Force $StageDir -ErrorAction SilentlyContinue
    }

    if ($Failed) {
        exit 1
    }
}
