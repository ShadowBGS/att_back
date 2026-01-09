# Run the backend (dev)
# 1) Copy .env.example -> .env and fill DATABASE_URL and FIREBASE_SERVICE_ACCOUNT_FILE
# 2) Install deps: pip install -r requirements.txt
# 3) Run: uvicorn app.main:app --reload --port 8000

$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) {
  Write-Host "Missing backend/.env. Copy .env.example to .env and fill it." -ForegroundColor Yellow
}

Set-Location $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (Test-Path $venvPython) {
  & $venvPython -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --app-dir $PSScriptRoot
} else {
  python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --app-dir $PSScriptRoot
}
