$py = 'C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe'
Remove-Item C:\arena\onnx_load2.txt, C:\arena\onnx_load2_err.txt -ErrorAction SilentlyContinue
$p = Start-Process -FilePath $py -ArgumentList '-X','utf8','C:\arena\test_onnx_load.py' `
     -RedirectStandardOutput 'C:\arena\onnx_load2.txt' -RedirectStandardError 'C:\arena\onnx_load2_err.txt' `
     -PassThru -WindowStyle Hidden
if (-not $p.WaitForExit(120000)) {
    $p.Kill()
    Write-Output 'TIMEOUT after 120s (session creation still hanging)'
} else {
    Write-Output ('exit=' + $p.ExitCode)
}
Write-Output '--- stdout ---'
Get-Content C:\arena\onnx_load2.txt -Encoding UTF8 -ErrorAction SilentlyContinue
Write-Output '--- stderr ---'
Get-Content C:\arena\onnx_load2_err.txt -Encoding UTF8 -ErrorAction SilentlyContinue
