#!/bin/bash
cd "$(dirname "$0")"
echo "=== Ders Anlatıcı kurulumu ==="
if ! command -v python3 >/dev/null; then echo "Python bulunamadı: https://www.python.org/downloads/ adresinden kur."; open https://www.python.org/downloads/; exit 1; fi
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt && echo "Kurulum tamam! Şimdi \"Ders Anlatici.command\" dosyasına çift tıkla."
