$s = (Get-Counter "\Processor(_Total)\% Processor Time" -SampleInterval 2 -MaxSamples 6).CounterSamples | ForEach-Object { $_.CookedValue }
$avg = [math]::Round(($s | Measure-Object -Average).Average, 1)
Write-Output ("cpu_avg=" + $avg + " procs=" + (Get-Process python -ErrorAction SilentlyContinue).Count)
Get-Content C:\arena\pool.log -ErrorAction SilentlyContinue | Select-String "s/半庄" | Select-Object -Last 4 | ForEach-Object { $_.Line }
