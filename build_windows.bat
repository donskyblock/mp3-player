@echo off
setlocal

if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
)

py -m pip install --upgrade pyinstaller
if errorlevel 1 python -m pip install --upgrade pyinstaller

py -m PyInstaller --noconfirm --clean --windowed --name PulsePlayer main.py
if errorlevel 1 python -m PyInstaller --noconfirm --clean --windowed --name PulsePlayer main.py

echo Windows build complete: dist\PulsePlayer\
endlocal
