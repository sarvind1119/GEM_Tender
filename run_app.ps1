param(
    [switch]$Legacy
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw @"
The project environment is missing.

Create it from this folder, then run this command again:
  python -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -r requirements_web.txt

The launcher intentionally does not fall back to another Python installation.
"@
}

& $VenvPython -c "import streamlit; assert tuple(map(int, streamlit.__version__.split('.')[:2])) >= (1, 37)"
if ($LASTEXITCODE -ne 0) {
    throw "The project environment does not contain a supported Streamlit version. Reinstall requirements_web.txt."
}

$AppFile = if ($Legacy) { "legacy_app.py" } else { "app.py" }
& $VenvPython -m streamlit run (Join-Path $ProjectRoot $AppFile)
