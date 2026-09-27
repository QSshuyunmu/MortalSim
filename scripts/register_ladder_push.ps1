# Register "ArenaLadderPush" (every 3 hours) and disable the legacy "ArenaPoolPush".
# ASCII-only on purpose: PowerShell 5.1 reads BOM-less .ps1 as ANSI and Chinese
# text inside breaks the parser.
$ErrorActionPreference = "Stop"

$name = "ArenaLadderPush"
$script = "D:\tenhoulib\.diag\ladder_push.ps1"

# anchor at the next multiple of 3 hours from midnight
$now = Get-Date
$next = $now.Date.AddHours([math]::Floor($now.Hour / 3) * 3 + 3)
Write-Output ("anchor = " + $next.ToString("yyyy-MM-dd HH:mm:ss"))

$action = New-ScheduledTaskAction -Execute "powershell" `
    -Argument ("-NoProfile -ExecutionPolicy Bypass -File " + $script)
$trigger = New-ScheduledTaskTrigger -Once -At $next -RepetitionInterval (New-TimeSpan -Hours 3)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew

if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Output "removed existing $name"
}
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings | Out-Null
Write-Output ("registered " + $name)

$t = Get-ScheduledTask -TaskName $name
Write-Output ("  interval = " + $t.Triggers[0].Repetition.Interval)
Write-Output ("  state    = " + $t.State)

# legacy: disable, do not delete (keeps a rollback path)
$old = Get-ScheduledTask -TaskName "ArenaPoolPush" -ErrorAction SilentlyContinue
if ($old) {
    Disable-ScheduledTask -TaskName "ArenaPoolPush" | Out-Null
    Write-Output ("ArenaPoolPush -> " + (Get-ScheduledTask -TaskName "ArenaPoolPush").State)
} else {
    Write-Output "ArenaPoolPush not found"
}
