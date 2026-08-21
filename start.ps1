$runner = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $runner) { throw '未找到 Python。请安装 Python 3.10 或更高版本。' }
& $runner (Join-Path $PSScriptRoot 'server.py') --port 8000
