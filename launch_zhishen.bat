@echo off
cd /d "%~dp0"
set "PYTHONW=%~dp0..\python\.venv\Scripts\pythonw.exe"
if not exist "%PYTHONW%" exit /b 1
start "" "%PYTHONW%" "%~dp0zhishen_alert_gui.pyw"
