# List python/powershell processes with command lines. ASCII-only, no Chinese.
$ErrorActionPreference = "Continue"
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name='powershell.exe'" |
  Select-Object ProcessId, ParentProcessId, @{n='Cmd';e={
      $c = $_.CommandLine
      if ($c -and $c.Length -gt 110) { $c.Substring(0,110) } else { $c }
  }} |
  Sort-Object ProcessId |
  Format-List
