$ErrorActionPreference = "Continue"
taskkill /F /IM python.exe 2>&1 | Out-Null
Start-Sleep -Seconds 3
Copy-Item -Force C:\arena\backup\libriichi.pyd.orig C:\arena\libriichi.pyd
Write-Output ("pyd restored = " + (Get-Item C:\arena\libriichi.pyd).Length)
