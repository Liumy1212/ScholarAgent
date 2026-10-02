[CmdletBinding()]
param(
    [string]$AgentEnvironment = 'airesearcher-agent'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$ChecksRoot = Join-Path $RepositoryRoot '.private\checks\phase-1-5'
$FrontendDist = Join-Path $ChecksRoot 'frontend-dist'
$MypyCache = Join-Path $ChecksRoot 'mypy-cache'

function Write-Step {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Get-RequiredCommand {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$InstallHint
    )
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "未找到 $Name。$InstallHint"
    }
    return $command.Source
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string]$FailureMessage
    )
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw $FailureMessage
        }
    } finally {
        Pop-Location
    }
}

$Node = Get-RequiredCommand -Name 'node' -InstallHint '请安装仓库要求的 Node.js。'
$Conda = Get-RequiredCommand -Name 'conda' -InstallHint '请安装 Conda 并创建 Agent 隔离环境。'
$Git = Get-RequiredCommand -Name 'git' -InstallHint '请安装 Git。'
$FrontendBin = Join-Path $RepositoryRoot 'frontend\node_modules\.bin'
$RequiredFrontendCommands = @('eslint.CMD', 'tsc.CMD', 'vitest.CMD', 'vite.CMD')
foreach ($command in $RequiredFrontendCommands) {
    if (-not (Test-Path -LiteralPath (Join-Path $FrontendBin $command) -PathType Leaf)) {
        throw "Frontend 依赖不完整，缺少 $command。请先在 frontend/ 执行 pnpm install。"
    }
}

New-Item -ItemType Directory -Path $ChecksRoot -Force | Out-Null

Write-Step '校验 Contracts'
Invoke-Checked `
    -FilePath $Node `
    -Arguments @('validation/validate-contracts.mjs') `
    -WorkingDirectory (Join-Path $RepositoryRoot 'contracts') `
    -FailureMessage 'Contracts 校验失败。'

Write-Step '校验 Python Agent'
$AgentDirectory = Join-Path $RepositoryRoot 'agent'
$AgentCommands = @(
    ,@('run', '-n', $AgentEnvironment, 'python', '-m', 'ruff', 'check', '--no-cache', '.')
    ,@('run', '-n', $AgentEnvironment, 'python', '-m', 'ruff', 'format', '--check', '--no-cache', '.')
    ,@('run', '-n', $AgentEnvironment, 'python', '-m', 'mypy', '--cache-dir', $MypyCache)
    ,@('run', '-n', $AgentEnvironment, 'python', '-m', 'pytest', '-p', 'no:cacheprovider')
)
# conda run 在 GBK 控制台回显非 ASCII 输出时会以 UnicodeEncodeError 崩溃，强制子进程使用 UTF-8。
$PreviousPythonIoEncoding = $env:PYTHONIOENCODING
$env:PYTHONIOENCODING = 'utf-8'
try {
    foreach ($arguments in $AgentCommands) {
        Invoke-Checked `
            -FilePath $Conda `
            -Arguments $arguments `
            -WorkingDirectory $AgentDirectory `
            -FailureMessage "Agent 检查失败：conda $($arguments -join ' ')"
    }
} finally {
    if ($null -eq $PreviousPythonIoEncoding) {
        Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONIOENCODING = $PreviousPythonIoEncoding
    }
}

Write-Step '校验 Java Backend'
$PreviousMavenUserHome = $env:MAVEN_USER_HOME
$env:MAVEN_USER_HOME = Join-Path $env:USERPROFILE '.m2'
try {
    Invoke-Checked `
        -FilePath (Join-Path $RepositoryRoot 'backend\mvnw.cmd') `
        -Arguments @(
            'verify',
            "-Dmaven.repo.local=$(Join-Path $ChecksRoot 'maven-repository')"
        ) `
        -WorkingDirectory (Join-Path $RepositoryRoot 'backend') `
        -FailureMessage 'Backend verify 失败。'
} finally {
    if ($null -eq $PreviousMavenUserHome) {
        Remove-Item Env:MAVEN_USER_HOME -ErrorAction SilentlyContinue
    } else {
        $env:MAVEN_USER_HOME = $PreviousMavenUserHome
    }
}

Write-Step '校验 React Frontend'
$FrontendDirectory = Join-Path $RepositoryRoot 'frontend'
Invoke-Checked `
    -FilePath (Join-Path $FrontendBin 'eslint.CMD') `
    -Arguments @('.', '--max-warnings', '0') `
    -WorkingDirectory $FrontendDirectory `
    -FailureMessage 'Frontend lint 失败。'
foreach ($project in @('tsconfig.app.json', 'tsconfig.node.json')) {
    Invoke-Checked `
        -FilePath (Join-Path $FrontendBin 'tsc.CMD') `
        -Arguments @('--noEmit', '--pretty', 'false', '--incremental', 'false', '-p', $project) `
        -WorkingDirectory $FrontendDirectory `
        -FailureMessage "Frontend 类型检查失败：$project"
}
Invoke-Checked `
    -FilePath (Join-Path $FrontendBin 'vitest.CMD') `
    -Arguments @('run', '--configLoader', 'runner') `
    -WorkingDirectory $FrontendDirectory `
    -FailureMessage 'Frontend 测试失败。'
Invoke-Checked `
    -FilePath (Join-Path $FrontendBin 'vite.CMD') `
    -Arguments @('build', '--configLoader', 'runner', '--outDir', $FrontendDist, '--emptyOutDir') `
    -WorkingDirectory $FrontendDirectory `
    -FailureMessage 'Frontend 生产构建失败。'

Write-Step '检查 Git 差异格式'
Invoke-Checked `
    -FilePath $Git `
    -Arguments @('-C', $RepositoryRoot, 'diff', '--check') `
    -WorkingDirectory $RepositoryRoot `
    -FailureMessage 'git diff --check 失败。'

Write-Host "`n阶段 1.5 本地回归全部通过。" -ForegroundColor Green
