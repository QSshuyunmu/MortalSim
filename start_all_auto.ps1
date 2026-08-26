$env:NO_PROXY="127.0.0.1,localhost"
$env:no_proxy="127.0.0.1,localhost"
$ErrorActionPreference = "Continue"
$root = "D:\tenhoulib\MortalSim-Bot"
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"=== autostart $stamp ===" | Out-File (Join-Path $logs "autostart.log") -Encoding utf8

# 1. OCR
Start-Process -FilePath "E:\riichi-vision\.venv\Scripts\python.exe" `
  -ArgumentList "-m","uvicorn","riichi_vision.app:app","--app-dir","backend","--host","127.0.0.1","--port","8000" `
  -WorkingDirectory "E:\riichi-vision" -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $logs "ocr.log") -RedirectStandardError (Join-Path $logs "ocr.err")
"OCR started" | Out-File (Join-Path $logs "autostart.log") -Append -Encoding utf8

# 2. MortalSim
Start-Process -FilePath "cmd.exe" -ArgumentList "/c","`"$root\start_mortalsim.cmd`"" -WindowStyle Hidden
"MortalSim started" | Out-File (Join-Path $logs "autostart.log") -Append -Encoding utf8

# 3. Bot
Remove-Item (Join-Path $root "data\bot.lock") -Force -ErrorAction SilentlyContinue
Start-Process -FilePath "C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe" `
  -ArgumentList "src\bot.py" -WorkingDirectory $root -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $logs "bot.log") -RedirectStandardError (Join-Path $logs "bot.err")
"Bot started" | Out-File (Join-Path $logs "autostart.log") -Append -Encoding utf8

# 4. NapCat quick login (detached; needs admin, task already runs elevated)
Start-Process -FilePath "cmd.exe" -ArgumentList "/c","`"$root\napcat_shell\start_napcat_quick.cmd`"" -WindowStyle Hidden
"NapCat quick login started" | Out-File (Join-Path $logs "autostart.log") -Append -Encoding utf8