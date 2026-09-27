$tr = 'powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\arena\health_run.ps1'
schtasks /Create /TN "ArenaHealth30m" /TR $tr /SC MINUTE /MO 30 /F | Out-Null
schtasks /Query /TN "ArenaHealth30m" /FO LIST | Select-String "TaskName|Status|Next Run Time"
Write-Output "--- registered ---"
