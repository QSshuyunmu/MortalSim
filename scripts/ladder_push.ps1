# Ladder standings -> QQ group push (every 3 hours).
# Data flow mirrors the legacy pool pusher: remote builds the stats table,
# local formats and sends (the OneBot HTTP endpoint lives on this machine).
$ErrorActionPreference = "Continue"
$py = 'C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe'
$stamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
$log = "D:\tenhoulib\.diag\push_log.txt"

# 1) remote: aggregate ladder_results.db by physical model -> C:/arena/_ladder_stats.tsv
ssh new-machine "powershell -Command C:/Users/23610/AppData/Local/Programs/Python/Python313/python.exe -X utf8 C:/arena/ladder_stats_export.py" 2>&1 | Out-Null

# 2) pull it back
scp -q new-machine:C:/arena/_ladder_stats.tsv "D:\tenhoulib\.diag\ladder_stats.tsv" 2>&1 | Out-Null
if (-not (Test-Path "D:\tenhoulib\.diag\ladder_stats.tsv")) {
    "[$stamp] FATAL: ladder_stats.tsv not fetched" | Add-Content $log
    exit 1
}
$fresh = (Get-Item "D:\tenhoulib\.diag\ladder_stats.tsv").LastWriteTime
"[$stamp] ladder push start (tsv $fresh)" | Add-Content $log

# 3) format + send
& $py -X utf8 "D:\tenhoulib\.diag\ladder_push.py" 2>&1 | Add-Content $log
