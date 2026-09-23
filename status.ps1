$port = 8000
$conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    Write-Host "Proxy running on port $port (PID $($conns[0].OwningProcess))"
    try {
        $h = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 5
        Write-Host "  Upstream: $($h.upstream)"
        Write-Host "  Model:    $($h.model)"
        Write-Host "  Stats:    $($h.stats | ConvertTo-Json -Compress)"
    } catch {
        Write-Host "  Health check failed: $($_.Exception.Message)"
    }
} else {
    Write-Host "No proxy listening on port $port"
}