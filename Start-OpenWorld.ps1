param(
    [switch]$PrepareOnly,
    [switch]$NoBrowser,
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'

function Invoke-Checked {
    param([string]$File, [string[]]$Arguments)
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$File failed (exit code $LASTEXITCODE)."
    }
}

function Find-NativePython {
    $candidates = @($VenvPython)
    foreach ($command in @(Get-Command python.exe -All -ErrorAction SilentlyContinue)) {
        if ($command.Source -notlike '*\WindowsApps\*') { $candidates += $command.Source }
    }
    foreach ($registry in @(
        'HKCU:\Software\Python\PythonCore',
        'HKLM:\Software\Python\PythonCore',
        'HKLM:\Software\WOW6432Node\Python\PythonCore'
    )) {
        if (Test-Path -LiteralPath $registry) {
            foreach ($version in Get-ChildItem -LiteralPath $registry) {
                $install = Join-Path $version.PSPath 'InstallPath'
                if (Test-Path -LiteralPath $install) {
                    $path = (Get-Item -LiteralPath $install).GetValue('')
                    if ($path) { $candidates += Join-Path $path 'python.exe' }
                }
            }
        }
    }
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (Test-Path -LiteralPath $candidate) {
            "import sys; sys.exit(0 if sys.platform == 'win32' and sys.version_info >= (3, 12) else 1)" |
                & $candidate -
            if ($LASTEXITCODE -eq 0) { return $candidate }
        }
    }
    return $null
}

function Find-Node {
    $candidates = @(
        (Join-Path $env:ProgramFiles 'nodejs\node.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\nodejs\node.exe')
    )
    foreach ($command in @(Get-Command node.exe -All -ErrorAction SilentlyContinue)) {
        $candidates += $command.Source
    }
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (Test-Path -LiteralPath $candidate) {
            $version = & $candidate --version
            if ($LASTEXITCODE -eq 0 -and $version -match '^v(\d+)\.' -and [int]$Matches[1] -ge 22) {
                return $candidate
            }
        }
    }
    return $null
}

function Install-Prerequisite {
    param([string]$Id)
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Install native Python 3.12+ and Node.js 22+ first, then start again. Windows Package Manager (winget) is unavailable."
    }
    Write-Host "Installing prerequisite: $Id"
    Invoke-Checked -File $winget.Source -Arguments @(
        'install', '--id', $Id, '--exact', '--source', 'winget',
        '--accept-source-agreements', '--accept-package-agreements'
    )
}

function Read-Health {
        param([string]$Url)
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "$Url/api/health" -TimeoutSec 2
        return $response.Content | ConvertFrom-Json
    } catch [System.Net.WebException] {
        return $null
    }
}

$server = $null
try {
    Set-Location $Root
    if ($Port -lt 1 -or $Port -gt 65535) { throw 'Port must be between 1 and 65535.' }
    Write-Host 'Checking Python and Node.js...'
    $python = Find-NativePython
    if (-not $python) {
        Install-Prerequisite 'Python.Python.3.12'
        $python = Find-NativePython
        if (-not $python) { throw 'Native Windows Python 3.12+ was not found after installation.' }
    }
    $node = Find-Node
    if (-not $node) {
        Install-Prerequisite 'OpenJS.NodeJS.LTS'
        $node = Find-Node
        if (-not $node) { throw 'Node.js 22+ was not found after installation.' }
    }
    $env:PATH = "$(Split-Path $node);$env:PATH"
    $npm = Join-Path (Split-Path $node) 'npm.cmd'
    if (-not (Test-Path -LiteralPath $npm)) { throw 'npm.cmd is missing from the Node.js installation.' }

    if (-not (Test-Path -LiteralPath $VenvPython)) {
        Write-Host 'Creating the local Python environment...'
        Invoke-Checked -File $python -Arguments @('-m', 'venv', (Join-Path $Root '.venv'))
    }
    $requirements = Join-Path $Backend 'requirements-lock.txt'
    $pythonStamp = Join-Path $Root '.venv\.openworld-requirements'
    $requirementsHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
    "import importlib.util, sys; sys.exit(0 if all(importlib.util.find_spec(name) for name in ['fastapi', 'uvicorn', 'sqlalchemy', 'alembic', 'httpx', 'cryptography', 'tiktoken']) else 1)" |
        & $VenvPython -
    $missingPython = $LASTEXITCODE -ne 0
    $changedPython = (Test-Path -LiteralPath $pythonStamp) -and
        ((Get-Content -LiteralPath $pythonStamp -Raw).Trim() -ne $requirementsHash)
    if ($missingPython -or $changedPython) {
        Write-Host 'Installing backend dependencies...'
        Invoke-Checked -File $VenvPython -Arguments @(
            '-m', 'pip', 'install', '--disable-pip-version-check', '-r', $requirements
        )
    }
    Invoke-Checked -File $VenvPython -Arguments @('-m', 'pip', 'check')
    Set-Content -LiteralPath $pythonStamp -Value $requirementsHash -Encoding ASCII
    $appProbe = @'
import importlib.metadata
import importlib.util
import sys
import tomllib
from pathlib import Path
root = Path.cwd()
spec = importlib.util.find_spec('app')
expected = (root / 'backend' / 'app' / '__init__.py').resolve()
version = tomllib.loads((root / 'backend' / 'pyproject.toml').read_text())['project']['version']
try:
    installed = importlib.metadata.version('openworld')
except importlib.metadata.PackageNotFoundError:
    installed = None
valid = spec is not None and spec.origin is not None and Path(spec.origin).resolve() == expected
sys.exit(0 if valid and installed == version else 1)
'@
    $appProbe | & $VenvPython -
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installing the OpenWorld backend package...'
        Invoke-Checked -File $VenvPython -Arguments @(
            '-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps', '-e', $Backend
        )
    }

    Set-Location $Frontend
    $nodeStamp = Join-Path $Frontend 'node_modules\.openworld-package-lock'
    $packageHash = (Get-FileHash -LiteralPath (Join-Path $Frontend 'package-lock.json') -Algorithm SHA256).Hash
    & $node -e "try { require.resolve('vite'); require.resolve('typescript') } catch (error) { if (error.code === 'MODULE_NOT_FOUND') process.exit(1); throw error }"
    $missingNode = $LASTEXITCODE -ne 0
    $changedNode = (Test-Path -LiteralPath $nodeStamp) -and
        ((Get-Content -LiteralPath $nodeStamp -Raw).Trim() -ne $packageHash)
    if ($missingNode -or $changedNode) {
        Write-Host 'Installing frontend dependencies...'
        Invoke-Checked -File $npm -Arguments @('ci', '--no-audit', '--no-fund')
    }
    Set-Content -LiteralPath $nodeStamp -Value $packageHash -Encoding ASCII
    Invoke-Checked -File $npm -Arguments @('run', 'build')

    Set-Location $Backend
    $env:OPENWORLD_FRONTEND_DIR = Join-Path $Frontend 'dist'
    if (-not $env:OPENWORLD_DATA_DIR -and -not $env:OPENWORLD_DATABASE_URL) {
        $env:OPENWORLD_DATA_DIR = Join-Path $Backend 'data'
    }
    Invoke-Checked -File $VenvPython -Arguments @('-m', 'alembic', 'upgrade', 'head')
    if ($PrepareOnly) { Write-Host 'OpenWorld setup verified.'; exit 0 }

    $url = "http://127.0.0.1:$Port"
    $health = Read-Health $url
    if ($health -and $health.status -eq 'ok' -and $health.phase -eq 1) {
        $index = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 5
        if ($index.Content -notmatch '<title>OpenWorld</title>') {
            throw 'Port is already used by a backend without the OpenWorld interface. Stop that backend or start with -Port 8001.'
        }
        Write-Host "OpenWorld is already running: $url"
        if (-not $NoBrowser) { Start-Process $url }
        exit 0
    }
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try { $listener.Start() }
    catch [System.Net.Sockets.SocketException] {
        throw "Port $Port is already in use. Start with a different -Port value."
    } finally { $listener.Stop() }

    Write-Host "Starting OpenWorld at $url"
    $server = Start-Process -FilePath $VenvPython -WorkingDirectory $Backend -NoNewWindow -PassThru `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port")
    $ready = $false
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        if ($server.HasExited) { throw "Backend exited with code $($server.ExitCode)." }
        $health = Read-Health $url
        if ($health -and $health.status -eq 'ok') { $ready = $true; break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) { throw "Backend did not become ready at $url." }
    if (-not $NoBrowser) { Start-Process $url }
    Write-Host 'OpenWorld is running. Close this window or press Ctrl+C to stop.'
    $server.WaitForExit()
    if ($server.ExitCode -ne 0) { throw "Backend exited with code $($server.ExitCode)." }
} finally {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id }
    Set-Location $Root
}
