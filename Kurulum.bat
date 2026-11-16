@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Ders Anlatici kurulumu ===
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python bulunamadi. https://www.python.org/downloads/ adresinden Python 3.12 kur.
  echo Kurarken EN ALTTAKI "Add python.exe to PATH" kutusunu isaretle, sonra bu dosyaya tekrar cift tikla.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)
if not exist .venv (
  echo Sanal ortam olusturuluyor...
  python -m venv .venv
)
echo Paketler yukleniyor (ilk seferde birkac dakika surer)...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo Kurulumda hata oldu. Ekrandaki mesaji bana gonder.
  pause
  exit /b 1
)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kisayol.ps1"
echo.
echo Kurulum tamam! Masaustundeki "Ders Anlatici" simgesine cift tikla.
echo (Uygulama her acilista guncellemeleri kendisi ceker.)
pause
