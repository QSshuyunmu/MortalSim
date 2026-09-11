<#
  注册 / 修复 MortalSim-Bot 开机与登录自启动计划任务
  ------------------------------------------------------------------
  历史缺陷（"服务无法持久化"的主因）：
    • DisallowStartIfOnBatteries=True / StopIfGoingOnBatteries=True
      → 笔记本一旦使用电池：开机不启动；运行中切到电池会被直接杀死。
    • ExecutionTimeLimit=PT72H → 任务满 72 小时被强制结束（连带 bot.py 与后端）。
    • RestartCount=0 → 进程崩溃后计划任务层面无任何重试。
    • 仅 LogonTrigger → 无交互登录（如远程/自动登录）时不触发。
  本脚本以电池友好 + 无限时长 + 失败重启 + 开机/登录双触发的方式重建任务。
  需以管理员权限运行（脚本会自动提权）。
#>
[CmdletBinding()]
param(
  [string]$TaskName = "MortalSimBotAutoStart"
)

$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Host "需要管理员权限，正在提权..."
  Start-Process powershell -Verb runAs -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`""
  )
  exit
}

$root = "D:\tenhoulib\MortalSim-Bot"
$target = Join-Path $root "start_all_services.ps1"
if (-not (Test-Path $target)) { throw "missing $target" }

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$target`""

# 开机 + 登录双触发，覆盖自动登录 / 远程登录等场景
$triggers = @(
  (New-ScheduledTaskTrigger -AtStartup),
  (New-ScheduledTaskTrigger -AtLogOn)
)

# 关键：电池友好 + 无执行时长上限 + 失败自动重试 + 错过后尽快补跑
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -RestartCount 3 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -MultipleInstances IgnoreNew `
  -Priority 4

# 必须用 Interactive：NapCat 需要真实桌面会话才能拉起 QQ.exe
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
  -Settings $settings -Principal $taskPrincipal -Force `
  -Description "MortalSim-Bot: 开机/登录自动拉起 MortalSim 后端与 QQ Bot 守护进程（电池友好、无限时长）。" | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
Write-Host "已注册计划任务: $TaskName"
$task.Settings | Format-List DisallowStartIfOnBatteries, StopIfGoingOnBatteries, ExecutionTimeLimit, RestartCount, RestartInterval, StartWhenAvailable
$task.Triggers | ForEach-Object { "trigger: " + $_.CimClass.CimClassName }
