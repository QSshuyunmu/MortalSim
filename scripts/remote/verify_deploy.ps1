$names = 'pool_arena.py','arena_daemon.ps1','restart_task.ps1','health_run.ps1','health_collect.py','bench_conc.py','st9.ps1'
foreach ($n in $names) {
    $p = 'C:\arena\' + $n
    if (Test-Path $p) {
        $i = Get-Item $p
        Write-Output ($i.Name.PadRight(20) + ' size=' + $i.Length.ToString().PadLeft(6) + '  mtime=' + $i.LastWriteTime.ToString('MM-dd HH:mm'))
    } else {
        Write-Output ($n.PadRight(20) + ' MISSING')
    }
}
$g = Get-FileHash 'C:\arena\pool_arena.py' -Algorithm SHA256
Write-Output ('pool_arena.py sha256=' + $g.Hash.Substring(0,16))
$g2 = Get-FileHash 'C:\arena\arena_daemon.ps1' -Algorithm SHA256
Write-Output ('arena_daemon.ps1 sha256=' + $g2.Hash.Substring(0,16))
Write-Output ('python procs=' + (Get-Process python -ErrorAction SilentlyContinue).Count)
Write-Output ('STOP exists=' + (Test-Path 'C:\arena\STOP'))
