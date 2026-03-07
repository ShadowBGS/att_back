# Backend Test Setup and Execution Script
# This script uses the existing Python virtual environment and runs the backend tests

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Backend Test Setup & Execution" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Navigate to backend directory
Set-Location $PSScriptRoot

# Check for existing venv at parent level (used by run.ps1)
$parentVenvPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$localVenvPython = Join-Path $PSScriptRoot "venv\Scripts\python.exe"

if (Test-Path $parentVenvPython) {
    $pythonExe = $parentVenvPython
    Write-Host "[1/4] Using existing parent venv: ..\.venv" -ForegroundColor Green
} elseif (Test-Path $localVenvPython) {
    $pythonExe = $localVenvPython
    Write-Host "[1/4] Using existing local venv: .\venv" -ForegroundColor Green
} else {
    Write-Host "[1/4] No virtual environment found" -ForegroundColor Yellow
    Write-Host "      Please run from project root: python -m venv .venv" -ForegroundColor Yellow
    Write-Host "      Or create local venv: python -m venv backend\venv" -ForegroundColor Yellow
    exit 1
}

$pythonVersion = & $pythonExe --version
Write-Host "      Python: $pythonVersion" -ForegroundColor Green
Write-Host ""

# Step 2: No activation needed - we'll use python.exe directly
Write-Host "[2/4] Python executable ready" -ForegroundColor Green
Write-Host ""

# Step 3: Install dependencies
Write-Host "[3/4] Installing dependencies..." -ForegroundColor Yellow
& $pythonExe -m pip install -q --upgrade pip
& $pythonExe -m pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install requirements" -ForegroundColor Red
    exit 1
}

# Install test dependencies
& $pythonExe -m pip install -q pytest httpx pytest-asyncio
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install test dependencies" -ForegroundColor Red
    exit 1
}
Write-Host "      Dependencies installed successfully" -ForegroundColor Green
Write-Host ""

# Step 4: Run tests
Write-Host "[4/4] Running backend tests..." -ForegroundColor Yellow
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host ""

& $pythonExe -m pytest tests/test_api.py -v --tb=short

Write-Host ""
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host "Test execution completed!" -ForegroundColor Green
Write-Host ""
Write-Host "To run tests again manually:" -ForegroundColor Yellow
Write-Host "  cd backend" -ForegroundColor White
Write-Host "  ..\.venv\Scripts\python.exe -m pytest tests/test_api.py -v" -ForegroundColor White
Write-Host ""
