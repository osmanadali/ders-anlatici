#!/bin/bash
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then .venv/bin/python baslat.py; else python3 baslat.py; fi
