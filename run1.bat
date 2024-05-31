@echo off
SETLOCAL
:: Load variables from .env file, ignoring comments and empty lines
for /f "usebackq tokens=* delims=" %%a in (`type .env ^| findstr /V /R "^\s*#" ^| findstr /R /V "^\s*$"`) do set "%%a"
python nameparser.py
python rubyparser.py
python nameaggregator.py
python nametranslator.py
ENDLOCAL