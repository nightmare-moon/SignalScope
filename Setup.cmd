@echo off
setlocal
cd /d "%~dp0"
echo SignalScope setup - Python 3.12 or newer is required.
echo This creates a private virtual environment and installs Bluetooth support.
py -3 -c "import sys; assert sys.version_info >= (3,12)" >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.12 or newer from https://www.python.org/downloads/windows/
  echo Include the Python launcher and Tcl/Tk. Then run Setup.cmd again.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if not exist ".venv\Scripts\python.exe" (
  echo Could not create the environment. Move this folder to a writable location.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo Bluetooth dependency installation failed. Check your internet connection.
  echo You can still try Wi-Fi using Start.cmd and unchecking Bluetooth LE.
  pause
  exit /b 1
)
echo Setup complete. Double-click Start.cmd to run or Demo.cmd to preview.
pause
