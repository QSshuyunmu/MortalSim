# Ladder status probe: processes, CPU delta over 20s, log tail. ASCII-only.
$ErrorActionPreference = "Continue"
Write-Output "=== python/powershell processes ==="
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
  Select-Object ProcessId, ParentProcessId, WorkingSetSize, Name | Format-Table -AutoSize

Write-Output "=== ladder python CPU (20s sample) ==="
$procs = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.WorkingSet64 -gt 500MB }
if ($procs) {
    $before = @{}
    foreach ($p in $procs) { $before[$p.Id] = $p.CPU }
    Start-Sleep -Seconds 20
    $after = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.WorkingSet64 -gt 500MB }
    foreach ($p in $after) {
        $b = $before[$p.Id]
        if ($null -ne $b) {
            $delta = [math]::Round($p.CPU - $b, 1)
            $cores = [math]::Round(($p.CPU - $b) / 20.0, 2)
            Write-Output ("pid={0} cpu20s={1}s (~{2} cores)" -f $p.Id, $delta, $cores)
        }
    }
} else {
    Write-Output "no big python process found"
}

Write-Output "=== ladder_stdout.log tail 12 ==="
Get-Content "C:\arena\ladder\ladder_stdout.log" -Tail 12 -Encoding UTF8

Write-Output "=== UI check (localhost) ==="
try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:28787/api/ladder/seasons/atozuke-ladder-v1?sort=rank" -TimeoutSec 10
    Write-Output ("UI HTTP {0}" -f $r.StatusCode)
} catch {
    Write-Output ("UI FAIL: {0}" -f $_.Exception.Message)
}
