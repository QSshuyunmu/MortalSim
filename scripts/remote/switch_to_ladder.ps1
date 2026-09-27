# Switch guardians: disable old pool tasks, register AtozukeLadderArena + AtozukeLadderUI.
# ASCII-only on purpose: Windows PowerShell 5.1 reads no-BOM files as ANSI.
$ErrorActionPreference = "Continue"

# 1. Disable old pool tasks (definitions kept for easy rollback via /ENABLE)
schtasks /Change /TN "AtozukeMahjongArena" /DISABLE
schtasks /Change /TN "ArenaPoolRestart6h" /DISABLE

# 2. Ladder guardian task (at startup + auto restart)
schtasks /Create /F /TN "AtozukeLadderArena" `
  /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\arena\ladder\daemon_ladder.ps1" `
  /SC ONSTART /RU SYSTEM /RL HIGHEST

# 3. UI API service task
schtasks /Create /F /TN "AtozukeLadderUI" `
  /TR "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe -X utf8 C:\arena\ladder\ladder_api_server.py --data-root C:\arena\ladder_ui_data --dist C:\arena\ladder_ui\dist --port 28787" `
  /SC ONSTART /RU SYSTEM /RL HIGHEST

# 4. Firewall rule for UI port
netsh advfirewall firewall delete rule name="AtozukeLadderUI" | Out-Null
netsh advfirewall firewall add rule name="AtozukeLadderUI" dir=in action=allow protocol=TCP localport=28787

# 5. Start both tasks now
schtasks /Run /TN "AtozukeLadderUI"
schtasks /Run /TN "AtozukeLadderArena"

Start-Sleep -Seconds 5
schtasks /Query /TN "AtozukeLadderArena" /FO LIST
schtasks /Query /TN "AtozukeLadderUI" /FO LIST
schtasks /Query /TN "AtozukeMahjongArena" /FO LIST
