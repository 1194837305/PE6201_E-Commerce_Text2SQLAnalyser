$localPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$runner = if (Test-Path -LiteralPath $localPython) { $localPython } else { (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $runner) { throw '未找到 Python。请安装 Python 3.10 或更高版本。' }
if (-not (Test-Path -LiteralPath $localPython)) { throw '请先运行 python -m venv .venv，然后安装依赖：.\.venv\Scripts\python.exe -m pip install -r requirements.txt' }
& $runner (Join-Path $PSScriptRoot 'server.py') --port 8000
