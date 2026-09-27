$ErrorActionPreference = "Continue"
New-Item -ItemType Directory -Force -Path C:\arena\backup | Out-Null
Copy-Item -Force C:\arena\libriichi.pyd C:\arena\backup\libriichi.pyd.orig -ErrorAction SilentlyContinue
taskkill /F /IM python.exe 2>&1 | Out-Null
Start-Sleep -Seconds 3
Copy-Item -Force C:\arena\test_pyd3\libriichi.cp313-win_amd64.pyd C:\arena\libriichi.pyd
Copy-Item -Force C:\arena\test_pyd3\onnxruntime.dll C:\arena\onnxruntime.dll
Write-Output ("pyd now = " + (Get-Item C:\arena\libriichi.pyd).Length + " | backup = " + (Get-Item C:\arena\backup\libriichi.pyd.orig).Length)
