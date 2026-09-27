# 30-min L1 health task (Atozuke). Collects metrics, then restarts the pool if the
# collector flagged a hard fault. Kept ASCII-only on purpose (see HANDOFF trap 8).
$py = 'C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe'
$log = 'C:\arena\health_task.log'
$stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')

try {
    $out = (& $py -X utf8 'C:\arena\health_collect.py' 2>&1 | Out-String).Trim()
    Add-Content $log "$stamp collect: $out"
} catch {
    Add-Content $log "$stamp collect FAILED: $_"
}

$act = 'ok'
if (Test-Path 'C:\arena\_health_action.txt') {
    $act = (Get-Content 'C:\arena\_health_action.txt' -First 1).Trim()
}
if ($act -eq 'restart') {
    Add-Content $log "$stamp ACTION=restart -> restart_task.ps1"
    & powershell -NoProfile -ExecutionPolicy Bypass -File 'C:\arena\restart_task.ps1' *>> $log
    Add-Content $log "$stamp restart finished"
} elseif ($act -eq 'alert') {
    Add-Content $log "$stamp ACTION=alert (notify only, no restart)"
}
