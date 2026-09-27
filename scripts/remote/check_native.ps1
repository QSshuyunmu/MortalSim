$py = 'C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe'
& $py -X utf8 -c "import libriichi, os; print('libriichi at', libriichi.__file__); print('has MortalOnnxEngine:', hasattr(libriichi.arena, 'MortalOnnxEngine')); print('arena attrs:', [a for a in dir(libriichi.arena) if not a.startswith('_')])"
Write-Output '--- pyd files on disk ---'
Get-ChildItem -Path C:\arena -Recurse -Filter 'libriichi*.pyd' -ErrorAction SilentlyContinue | ForEach-Object { Write-Output ($_.FullName + '  ' + $_.Length + '  ' + $_.LastWriteTime.ToString('MM-dd HH:mm')) }
Write-Output '--- site-packages libriichi ---'
& $py -X utf8 -c "import sys,glob,os; [print(p, os.path.getsize(p), __import__('time').strftime('%m-%d %H:%M', __import__('time').localtime(os.path.getmtime(p)))) for p in glob.glob(os.path.dirname(os.__file__)+'/../Lib/site-packages/libriichi*')+] if False else [print(p) for p in glob.glob(sys.prefix + '/Lib/site-packages/libriichi*')]"
