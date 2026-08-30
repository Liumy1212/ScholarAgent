[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [string]$EnvFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($EnvFile)) {
    $EnvFile = Join-Path $RepositoryRoot '.env'
} elseif (-not [System.IO.Path]::IsPathRooted($EnvFile)) {
    $EnvFile = Join-Path (Get-Location).Path $EnvFile
}
$EnvFile = [System.IO.Path]::GetFullPath($EnvFile)

function Write-Step {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Fail {
    param([Parameter(Mandatory)][string]$Message)
    throw $Message
}

function Get-RequiredCommand {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$InstallHint
    )
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        Fail "未找到 $Name。$InstallHint"
    }
    return $command.Source
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$FailureMessage
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        Fail $FailureMessage
    }
}

function Read-EnvironmentFile {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Fail "未找到环境文件 $Path。请先在仓库根目录执行 Copy-Item .\.env.example .\.env，再填写真实值。"
    }

    $values = @{}
    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith('#')) {
            continue
        }
        if ($line -notmatch '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            Fail "环境文件包含无效行：$rawLine"
        }
        $name = $Matches[1]
        $value = $Matches[2]
        if ($values.ContainsKey($name)) {
            Fail "环境文件中重复定义了 $name。"
        }
        $values[$name] = $value
    }
    return $values
}

function Require-EnvironmentValue {
    param(
        [Parameter(Mandatory)][hashtable]$Values,
        [Parameter(Mandatory)][string]$Name
    )
    if (-not $Values.ContainsKey($Name) -or [string]::IsNullOrWhiteSpace($Values[$Name])) {
        Fail ".env 缺少必填变量 $Name。"
    }
}

function Resolve-ConfiguredPath {
    param([Parameter(Mandatory)][string]$Value)
    if ([System.IO.Path]::IsPathRooted($Value)) {
        return [System.IO.Path]::GetFullPath($Value)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $RepositoryRoot $Value))
}

function Assert-OutsideRepository {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Value
    )
    $resolved = Resolve-ConfiguredPath -Value $Value
    $rootWithSeparator = $RepositoryRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    if ($resolved.Equals($RepositoryRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        $resolved.StartsWith($rootWithSeparator, [System.StringComparison]::OrdinalIgnoreCase)) {
        Fail "$Name 必须指向仓库外目录，当前值为 $resolved。"
    }
}

function Assert-PaperLibraryBoundary {
    param([Parameter(Mandatory)][string]$Value)
    $resolved = Resolve-ConfiguredPath -Value $Value
    $privateRoot = [System.IO.Path]::GetFullPath((Join-Path $RepositoryRoot '.private'))
    $privateRootWithSeparator = $privateRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    if ($resolved.Equals($privateRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not $resolved.StartsWith($privateRootWithSeparator, [System.StringComparison]::OrdinalIgnoreCase)) {
        Fail "AIRESEARCHER_PAPER_LIBRARY_DIR 必须位于仓库的 .private 子目录中，当前值为 $resolved。"
    }
    return $resolved
}

function Assert-GitIgnored {
    param(
        [Parameter(Mandatory)][string]$GitPath,
        [Parameter(Mandatory)][string]$Path
    )
    & $GitPath -C $RepositoryRoot check-ignore --quiet --no-index -- $Path
    if ($LASTEXITCODE -ne 0) {
        Fail "AIRESEARCHER_PAPER_LIBRARY_DIR 未被 Git 忽略：$Path。"
    }
}

function Assert-PortAvailable {
    param(
        [Parameter(Mandatory)][int]$Port,
        [Parameter(Mandatory)][string]$Service
    )
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        Fail "端口 $Port 已被占用，无法启动 $Service。请停止占用该端口的进程后重试。"
    }
}

function Start-DevelopmentTerminal {
    param(
        [Parameter(Mandatory)][string]$PowerShellPath,
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string]$Command
    )
    $escapedDirectory = $WorkingDirectory.Replace("'", "''")
    $escapedTitle = $Title.Replace("'", "''")
    $childCommand = "`$Host.UI.RawUI.WindowTitle = '$escapedTitle'; Set-Location -LiteralPath '$escapedDirectory'; $Command"
    Start-Process -FilePath $PowerShellPath -ArgumentList @(
        '-NoLogo',
        '-NoExit',
        '-Command',
        $childCommand
    ) | Out-Null
}

Write-Step '校验环境配置'
$EnvironmentValues = Read-EnvironmentFile -Path $EnvFile
$RequiredValues = @(
    'DEEPSEEK_API_KEY',
    'AIRESEARCHER_DB_HOST',
    'AIRESEARCHER_DB_PORT',
    'AIRESEARCHER_DB_NAME',
    'AIRESEARCHER_DB_USER',
    'AIRESEARCHER_DB_PASSWORD',
    'AIRESEARCHER_DB_ROOT_PASSWORD',
    'AIRESEARCHER_QDRANT_URL',
    'AIRESEARCHER_PAPER_LIBRARY_DIR',
    'AIRESEARCHER_MODEL_CACHE_DIR'
)
foreach ($name in $RequiredValues) {
    Require-EnvironmentValue -Values $EnvironmentValues -Name $name
}

$Placeholders = @(
    'replace-with-your-deepseek-api-key',
    'replace-with-application-database-password',
    'replace-with-separate-root-password'
)
foreach ($name in @('DEEPSEEK_API_KEY', 'AIRESEARCHER_DB_PASSWORD', 'AIRESEARCHER_DB_ROOT_PASSWORD')) {
    if ($EnvironmentValues[$name] -in $Placeholders) {
        Fail ".env 中的 $name 仍是占位符，请填入真实值。"
    }
}
if ($EnvironmentValues['AIRESEARCHER_DB_PASSWORD'] -eq $EnvironmentValues['AIRESEARCHER_DB_ROOT_PASSWORD']) {
    Fail 'AIRESEARCHER_DB_PASSWORD 与 AIRESEARCHER_DB_ROOT_PASSWORD 必须使用不同密码。'
}
$PaperLibraryDirectory = Assert-PaperLibraryBoundary -Value $EnvironmentValues['AIRESEARCHER_PAPER_LIBRARY_DIR']
Assert-OutsideRepository -Name 'AIRESEARCHER_MODEL_CACHE_DIR' -Value $EnvironmentValues['AIRESEARCHER_MODEL_CACHE_DIR']
if ($EnvironmentValues.ContainsKey('AIRESEARCHER_STORAGE_DIR') -and
    -not [string]::IsNullOrWhiteSpace($EnvironmentValues['AIRESEARCHER_STORAGE_DIR'])) {
    Assert-OutsideRepository -Name 'AIRESEARCHER_STORAGE_DIR' -Value $EnvironmentValues['AIRESEARCHER_STORAGE_DIR']
}

foreach ($entry in $EnvironmentValues.GetEnumerator()) {
    if ($entry.Key -ne 'AIRESEARCHER_DB_ROOT_PASSWORD') {
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
    }
}

Write-Step '检查本机工具与项目依赖'
$Pwsh = Get-RequiredCommand -Name 'pwsh' -InstallHint '请安装 PowerShell 7。'
$Docker = Get-RequiredCommand -Name 'docker' -InstallHint '请安装并启动 Docker Desktop。'
$Conda = Get-RequiredCommand -Name 'conda' -InstallHint '请安装 Miniconda 或 Anaconda。'
$Java = Get-RequiredCommand -Name 'java' -InstallHint '请安装 JDK 21。'
$Node = Get-RequiredCommand -Name 'node' -InstallHint '请安装 Node.js 22.13 或更高版本。'
$Pnpm = Get-RequiredCommand -Name 'pnpm' -InstallHint '请安装 pnpm 11。'
$Git = Get-RequiredCommand -Name 'git' -InstallHint '请安装 Git。'
$MavenWrapper = Join-Path $RepositoryRoot 'backend\mvnw.cmd'
if (-not (Test-Path -LiteralPath $MavenWrapper -PathType Leaf)) {
    Fail '未找到 backend/mvnw.cmd，仓库内容不完整。'
}
Assert-GitIgnored -GitPath $Git -Path $PaperLibraryDirectory

$javaVersion = (& $Java -version 2>&1 | Out-String)
if ($javaVersion -notmatch 'version "21[\.]') {
    Fail '需要 JDK 21。请确认 java -version 与 JAVA_HOME 指向 JDK 21。'
}
$nodeVersion = (& $Node --version).TrimStart('v')
if ([version]$nodeVersion -lt [version]'22.13.0') {
    Fail "需要 Node.js 22.13.0 或更高版本，当前为 $nodeVersion。"
}
$pnpmVersion = (& $Pnpm --version).Trim()
if ([version]$pnpmVersion -lt [version]'11.0.0' -or [version]$pnpmVersion -ge [version]'12.0.0') {
    Fail "需要 pnpm 11，当前为 $pnpmVersion。"
}

Invoke-Checked -FilePath $Docker -Arguments @(
    'version',
    '--format',
    '{{.Server.Version}}'
) -FailureMessage 'Docker Desktop 未启动或 Docker daemon 不可用。'
Invoke-Checked -FilePath $Conda -Arguments @(
    'run',
    '-n',
    'airesearcher-agent',
    'python',
    '-c',
    'import airesearcher_agent, alembic, uvicorn'
) -FailureMessage 'Conda 环境 airesearcher-agent 不存在或 Agent 依赖未安装。请按 docs/deployment.md 完成首次准备。'
Invoke-Checked -FilePath $Pnpm -Arguments @(
    '--dir',
    (Join-Path $RepositoryRoot 'frontend'),
    'exec',
    'vite',
    '--version'
) -FailureMessage 'Frontend 依赖未安装。请在 frontend 目录执行 pnpm install --frozen-lockfile。'

$ComposeFile = Join-Path $RepositoryRoot 'infrastructure\compose.yaml'
Invoke-Checked -FilePath $Docker -Arguments @(
    'compose',
    '--env-file',
    $EnvFile,
    '-f',
    $ComposeFile,
    'config',
    '--quiet'
) -FailureMessage 'Docker Compose 配置校验失败。请检查 .env 和 infrastructure/compose.yaml。'

if ($CheckOnly) {
    Write-Host "`n检查通过：配置、原件库边界、Git 忽略规则、本机工具与项目依赖均可用。" -ForegroundColor Green
    exit 0
}

Write-Step '准备本地论文原件库目录'
New-Item -ItemType Directory -Path (Join-Path $PaperLibraryDirectory 'originals') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $PaperLibraryDirectory '.staging') -Force | Out-Null

Write-Step '检查应用端口'
Assert-PortAvailable -Port 8000 -Service 'Agent API'
Assert-PortAvailable -Port 8080 -Service 'Java BFF'
Assert-PortAvailable -Port 5173 -Service 'React'

Write-Step '启动 MySQL 与 Qdrant'
Invoke-Checked -FilePath $Docker -Arguments @(
    'compose',
    '--env-file',
    $EnvFile,
    '-f',
    $ComposeFile,
    'up',
    '-d',
    'mysql',
    'qdrant'
) -FailureMessage 'MySQL/Qdrant 启动失败。请检查 Docker Desktop 日志和端口 3306/6333/6334。'

$mysqlContainer = (& $Docker compose --env-file $EnvFile -f $ComposeFile ps -q mysql).Trim()
if (-not $mysqlContainer) {
    Fail '未找到 MySQL Compose 容器。'
}
$mysqlHealthy = $false
for ($attempt = 1; $attempt -le 60; $attempt++) {
    $status = (& $Docker inspect --format '{{.State.Health.Status}}' $mysqlContainer 2>$null |
        Out-String).Trim()
    if ($status -eq 'healthy') {
        $mysqlHealthy = $true
        break
    }
    if ($status -eq 'unhealthy') {
        Fail 'MySQL 容器健康检查失败。请查看 docker compose logs mysql。'
    }
    Start-Sleep -Seconds 2
}
if (-not $mysqlHealthy) {
    Fail 'MySQL 在 120 秒内未达到 healthy 状态。'
}

$qdrantHealthy = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri 'http://127.0.0.1:6333/healthz' -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $qdrantHealthy = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $qdrantHealthy) {
    Fail 'Qdrant 在 60 秒内未通过健康检查。请查看 docker compose logs qdrant。'
}

Write-Step '执行 MySQL schema 迁移'
Push-Location (Join-Path $RepositoryRoot 'agent')
try {
    Invoke-Checked -FilePath $Conda -Arguments @(
        'run',
        '-n',
        'airesearcher-agent',
        'alembic',
        'upgrade',
        'head'
    ) -FailureMessage 'Alembic 迁移失败。请检查 MySQL 账户密码和容器日志。'
} finally {
    Pop-Location
}

Write-Step '在独立终端中启动四个应用'
Start-DevelopmentTerminal -PowerShellPath $Pwsh -Title 'AIResearcher - Agent API' -WorkingDirectory $RepositoryRoot -Command 'conda run -n airesearcher-agent python -m uvicorn airesearcher_agent.main:app --app-dir .\agent\src --host 127.0.0.1 --port 8000'
Start-DevelopmentTerminal -PowerShellPath $Pwsh -Title 'AIResearcher - Worker' -WorkingDirectory $RepositoryRoot -Command 'conda run -n airesearcher-agent python -m airesearcher_agent.worker.main'
Start-DevelopmentTerminal -PowerShellPath $Pwsh -Title 'AIResearcher - Java BFF' -WorkingDirectory (Join-Path $RepositoryRoot 'backend') -Command '.\mvnw.cmd spring-boot:run'
Start-DevelopmentTerminal -PowerShellPath $Pwsh -Title 'AIResearcher - React' -WorkingDirectory (Join-Path $RepositoryRoot 'frontend') -Command 'pnpm dev'

Write-Host @"

启动命令已发出。
  Web:       http://127.0.0.1:5173
  Java BFF:  http://127.0.0.1:8080
  Agent API: http://127.0.0.1:8000
  Qdrant:    http://127.0.0.1:6333

请在各应用终端中查看启动日志；使用 Ctrl+C 停止对应应用。
停止基础设施（不删除数据）：
  docker compose --env-file .\.env -f .\infrastructure\compose.yaml down
"@ -ForegroundColor Green
