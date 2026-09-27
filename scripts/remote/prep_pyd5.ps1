$ErrorActionPreference = "Continue"
Copy-Item -Force C:\arena\libriichi.pyd C:\arena\backup\libriichi.pyd.pool4p -ErrorAction SilentlyContinue
taskkill /F /IM python.exe 2>&1 | Out-Null
Start-Sleep -Seconds 3
Copy-Item -Force C:\arena\libriichi.pyd C:\arena\backup\libriichi.pyd.pool4p2 -ErrorAction SilentlyContinue
Write-Output ("backup = " + (Get-Item C:\arena\backup\libriichi.pyd.pool4p).Length)
