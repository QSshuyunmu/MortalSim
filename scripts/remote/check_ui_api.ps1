# Check the ladder UI API from Atozuke's own localhost. ASCII-only.
$ErrorActionPreference = "Continue"
$url = "http://127.0.0.1:28787/api/ladder/seasons/atozuke-ladder-v1?sort=rank"
Write-Output "URL: $url"
$sw = [System.Diagnostics.Stopwatch]::StartNew()
try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 60
    $sw.Stop()
    Write-Output ("LOCAL-OK status={0} bytes={1} elapsed={2}ms" -f $r.StatusCode, $r.RawContentLength, $sw.ElapsedMilliseconds)
    $j = $r.Content | ConvertFrom-Json
    Write-Output ("accounts={0} games={1}" -f $j.accounts.Count, $j.season.games)
    $first = $j.accounts[0]
    Write-Output ("row0 keys sample: games_houou={0} stable_dan_houou={1} games_tokujou={2} stable_dan_tokujou={3} agari_rate={4}" -f `
        $first.games_houou, $first.stable_dan_houou, $first.games_tokujou, $first.stable_dan_tokujou, $first.agari_rate)
} catch {
    $sw.Stop()
    Write-Output ("LOCAL-FAIL elapsed={0}ms : {1}" -f $sw.ElapsedMilliseconds, $_.Exception.Message)
}

Write-Output "--- seasons endpoint ---"
try {
    $r2 = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:28787/api/ladder/seasons" -TimeoutSec 30
    Write-Output ("seasons status={0} bytes={1}" -f $r2.StatusCode, $r2.RawContentLength)
} catch {
    Write-Output ("seasons FAIL: {0}" -f $_.Exception.Message)
}

Write-Output "--- ui process ---"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*ladder_api_server*" } |
  Select-Object ProcessId, WorkingSetSize, CommandLine | Format-List
