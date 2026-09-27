$ErrorActionPreference = "Continue"
Move-Item -Force C:\arena\models\tsypx\ext_mortal.pth C:\arena\models\tsypx\2024v4bestmini.pth -ErrorAction SilentlyContinue
Write-Output ("tsypx = " + ((Get-ChildItem C:\arena\models\tsypx\*.pth).Name -join ", "))
& 'C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe' -c "import sqlite3;c=sqlite3.connect('C:/arena/pool_results.db');c.execute('DELETE FROM pool_games');c.execute('DELETE FROM pool_progress');c.commit();print('pool_games/progress cleared')"
