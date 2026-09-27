Write-Output "--- exit log ---"
Get-Content 'C:\arena\v3_exit.txt' -ErrorAction SilentlyContinue -Tail 3
Write-Output "--- stdout tail (完成批次) ---"
Get-Content 'C:\arena\v3_stdout.log' -ErrorAction SilentlyContinue | Select-String '完成：' | Select-Object -Last 8 | ForEach-Object { $_.Line }
Write-Output "--- procs / CPU ---"
(Get-Process python -ErrorAction SilentlyContinue).Count
(Get-Counter '\Processor(_Total)\% Processor Time').CounterSamples.CookedValue
Write-Output "--- DB 进度 ---"
& 'C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe' -c "import sqlite3;c=sqlite3.connect('C:/arena/arena_results.db');print(c.execute('SELECT match_type, COUNT(*), COUNT(DISTINCT seed_idx) FROM completed_games GROUP BY match_type').fetchall())"
