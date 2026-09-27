Write-Output "=== 1v3 正式榜单（C:\arena\leaderboard.md）==="
Get-Content C:\arena\leaderboard.md -ErrorAction SilentlyContinue
Write-Output ""
Write-Output "=== 各对抗组的半庄数（DB）==="
Start-Process -FilePath "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe" -ArgumentList "C:/arena/db_probe.py" -Wait -NoNewWindow -RedirectStandardOutput "C:\arena\db_out.txt"
Get-Content C:\arena\db_out.txt
Write-Output "=== 各组牌谱文件数 ==="
Get-ChildItem C:\arena\logs -Directory | ForEach-Object { "$($_.Name): $((Get-ChildItem $_.FullName -Filter *.gz).Count)" }
