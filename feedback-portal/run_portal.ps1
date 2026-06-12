$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (Test-Path $bundledPython) {
  $python = $bundledPython
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
  $python = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  $python = "python"
} else {
  throw "Python nao encontrado. Instale Python 3 ou ajuste o caminho no run_portal.ps1."
}

Set-Location $projectRoot
& $python "backend\app.py"
