@echo off
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (.venv\Scripts\python.exe baslat.py --telefon) else (python baslat.py --telefon)
pause
