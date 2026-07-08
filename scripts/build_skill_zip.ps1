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
        $OutDir = "D:\skill_zip_test"
    }

    $ResolvedOutDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutDir)
    $ZipPath = Join-Path $ResolvedOutDir "tender-assistant-skill.zip"
    $StageDir = Join-Path ([System.IO.Path]::GetTempPath()) ("tender-assistant-skill-stage-" + [System.Guid]::NewGuid().ToString("N"))
    $UserReadme = Join-Path $SkillDir "README_skill_zip_user.md"
    $ResultsInterpretation = Join-Path $SkillDir "RESULTS_INTERPRETATION.md"

    if (-not (Test-Path $SkillDir)) {
        throw "Skill directory not found: $SkillDir"
    }

    if (-not (Test-Path (Join-Path $SkillDir "SKILL.md"))) {
        throw "SKILL.md not found in skill directory."
    }

    if (-not (Test-Path (Join-Path $SkillDir "run.py"))) {
        throw "run.py not found in skill directory."
    }

    if (-not (Test-Path $UserReadme)) {
        throw "README_skill_zip_user.md not found in skill directory: $UserReadme"
    }

    if (-not (Test-Path $ResultsInterpretation)) {
    throw "RESULTS_INTERPRETATION.md not found in skill directory: $ResultsInterpretation"
}

    # These folders are QA workspace placeholders; build staging stays in temp.
    New-Item -ItemType Directory -Force $ResolvedOutDir | Out-Null
    New-Item -ItemType Directory -Force (Join-Path $ResolvedOutDir "input") | Out-Null
    New-Item -ItemType Directory -Force (Join-Path $ResolvedOutDir "out") | Out-Null
    New-Item -ItemType Directory -Force (Join-Path $ResolvedOutDir "skill") | Out-Null

    Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue
    Copy-Item $UserReadme (Join-Path $ResolvedOutDir "README_skill_zip_user.md") -Force
    Copy-Item $ResultsInterpretation (Join-Path $ResolvedOutDir "RESULTS_INTERPRETATION.md") -Force
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
