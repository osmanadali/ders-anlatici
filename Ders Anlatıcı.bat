@echo off
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (.venv\Scripts\python.exe baslat.py) else (python baslat.py)
if errorlevel 1 pause
