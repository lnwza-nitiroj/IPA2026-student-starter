# Run the bot without Docker (Windows): loads .env, starts the webhook
# server and a cloudflared Quick Tunnel. The bot registers its Webex
# webhook automatically from the tunnel's metrics endpoint.
#
#   powershell -ExecutionPolicy Bypass -File scripts\run_local.ps1
#
# Stop with Ctrl+C.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Get-Content (Join-Path $root ".env") | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $name, $value = $line.Split("=", 2)
        [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), "Process")
    }
}

if (-not $env:WEBEX_BOT_TOKEN) { throw "WEBEX_BOT_TOKEN is empty in .env" }

$env:WEBHOOK_HOST = "127.0.0.1"
$env:WEBHOOK_PORT = "8000"
$env:TUNNEL_METRICS_URL = "http://127.0.0.1:2000"

$python = Join-Path $root ".venv\Scripts\python.exe"
$tunnel = Start-Process cloudflared -PassThru -NoNewWindow -ArgumentList @(
    "tunnel", "--no-autoupdate", "--metrics", "127.0.0.1:2000",
    "--url", "http://127.0.0.1:8000"
)
try {
    & $python -m app.webhook_server
}
finally {
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force }
}
