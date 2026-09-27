Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ForEach-Object {
    Write-Output ($_.ProcessId.ToString().PadRight(8) + $_.CreationDate.ToString('HH:mm:ss') + '  ' + $_.CommandLine)
}
Write-Output ('python_count=' + (Get-Process python -ErrorAction SilentlyContinue).Count)
Write-Output ('powershell_count=' + (Get-Process powershell -ErrorAction SilentlyContinue).Count)
Write-Output '--- bench_results.jsonl ---'
if (Test-Path 'C:\arena\bench_results.jsonl') { Get-Content 'C:\arena\bench_results.jsonl' } else { Write-Output '(none)' }
Write-Output '--- STOP ---'
Write-Output (Test-Path 'C:\arena\STOP')
