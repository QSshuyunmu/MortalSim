@echo off
rem Start QQ Bot (NapCat and MortalSim must be running first).
set "NO_PROXY=127.0.0.1,localhost"
set "no_proxy=127.0.0.1,localhost"
cd /d %~dp0
C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe src\bot.py
