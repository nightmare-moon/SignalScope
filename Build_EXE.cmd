@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Setup.cmd first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pip install pyinstaller
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name SignalScope --collect-all bleak app.py
if errorlevel 1 goto failed
echo Build complete: dist\SignalScope\SignalScope.exe
echo Keep the entire dist\SignalScope folder together when copying it.
pause
exit /b 0
:failed
echo Build failed. Review the messages above. Start.cmd remains available.
pause
exit /b 1
