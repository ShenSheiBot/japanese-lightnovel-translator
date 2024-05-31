@echo off
SETLOCAL
:: Load variables from .env file, ignoring comments and empty lines
for /f "usebackq tokens=* delims=" %%a in (`type .env ^| findstr /V /R "^\s*#" ^| findstr /R /V "^\s*$"`) do set "%%a"
python epubloader.py
ENDLOCAL