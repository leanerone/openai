$port = 8000
$procs = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
         Select-Object -ExpandProperty OwningProcess -Unique
if ($procs) {
    foreach ($pid in $procs) {
        Write-Host "Stopping PID $pid on port $port..."
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "No proxy listening on port $port"
}