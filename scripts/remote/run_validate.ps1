param([string]$seed = "910000000", [string]$count = "2")
$py = 'C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe'
$out = 'C:\arena\validate_out.txt'
Remove-Item $out -ErrorAction SilentlyContinue
& $py -X utf8 C:\arena\validate_native.py $seed $count 2>&1 | Out-File -Encoding utf8 $out
Write-Output "done -> $out"
Get-Content $out -Tail 25
