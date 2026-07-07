$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$SkillDir = Join-Path $RepoRoot "tender-assistant-skill"
$DistDir = Join-Path $RepoRoot "dist"
$StageDir = Join-Path $DistDir "tender-assistant-skill"
$ZipPath = Join-Path $DistDir "tender-assistant-skill.zip"

if (-not (Test-Path $SkillDir)) {
    throw "Skill directory not found: $SkillDir"
}

if (-not (Test-Path (Join-Path $SkillDir "SKILL.md"))) {
    throw "SKILL.md not found in skill directory."
}

if (-not (Test-Path (Join-Path $SkillDir "run.py"))) {
    throw "run.py not found in skill directory."
}

Remove-Item -Recurse -Force $StageDir -ErrorAction SilentlyContinue
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

Compress-Archive -Path (Join-Path $StageDir "*") -DestinationPath $ZipPath -Force

Write-Host "Skill zip created: $ZipPath"
Write-Host "Zip root contains SKILL.md, run.py, requirements.txt, AGENT_PROMPT.md, config/, prompts/, src/, docs/."
