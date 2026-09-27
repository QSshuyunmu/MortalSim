Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','C:\arena\v3_wrapper.ps1' -WindowStyle Hidden
Write-Output "wrapper booted"
