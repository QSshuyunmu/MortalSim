$ErrorActionPreference = "Continue"
Copy-Item -Force C:\arena\libriichi.pyd C:\arena\backup\libriichi.pyd.rank4p -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName "AtozukeMahjongArena" -ErrorAction SilentlyContinue
taskkill /F /IM python.exe 2>&1 | Out-Null
Start-Sleep -Seconds 5
Copy-Item -Force C:\arena\libriichi_new.dll C:\arena\libriichi.pyd
Write-Output ("pyd = " + (Get-Item C:\arena\libriichi.pyd).Length)
Start-ScheduledTask -TaskName "AtozukeMahjongArena"
