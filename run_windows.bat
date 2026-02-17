@echo off
setlocal

if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
)

py main.py
if errorlevel 1 python main.py

endlocal
