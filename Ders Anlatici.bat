@echo off
cd /d "%~dp0"
rem Siyah pencere olmadan baslar (ayrintilar veri\baslat.log dosyasinda)
if exist .venv\Scripts\pythonw.exe (
  start "" .venv\Scripts\pythonw.exe baslat.py
  exit /b 0
)
where pythonw >nul 2>nul
if not errorlevel 1 (
  start "" pythonw baslat.py
  exit /b 0
)
python baslat.py
if errorlevel 1 pause
