$s = (Get-Counter "\Processor(_Total)\% Processor Time" -SampleInterval 3 -MaxSamples 8).CounterSamples | ForEach-Object { $_.CookedValue }
$avg = [math]::Round(($s | Measure-Object -Average).Average,1)
$mx = [math]::Round(($s | Measure-Object -Maximum).Maximum,1)
$py = "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe"
$n1 = & $py -c "import sqlite3;print(sqlite3.connect('C:/arena/pool_results.db').execute('SELECT COUNT(*) FROM pool_games').fetchone()[0])"
Write-Output ("REMOTE cpu_avg=$avg cpu_max=$mx procs=" + (Get-Process python -ErrorAction SilentlyContinue).Count + " rows1=$n1")
Start-Sleep -Seconds 120
$n2 = & $py -c "import sqlite3;print(sqlite3.connect('C:/arena/pool_results.db').execute('SELECT COUNT(*) FROM pool_games').fetchone()[0])"
$s2 = (Get-Counter "\Processor(_Total)\% Processor Time" -SampleInterval 3 -MaxSamples 6).CounterSamples | ForEach-Object { $_.CookedValue }
Write-Output ("REMOTE2 cpu_avg=" + [math]::Round(($s2 | Measure-Object -Average).Average,1) + " rows2=$n2")
