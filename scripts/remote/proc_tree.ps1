$ErrorActionPreference = "Continue"
Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='python.exe' OR Name='pythonw.exe'" |
  Select-Object ProcessId, ParentProcessId, Name |
  Sort-Object Name, ProcessId |
  Format-Table -AutoSize
