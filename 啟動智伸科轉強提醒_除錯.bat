@echo off
chcp 65001 >nul
title 智伸科 4551 三層轉強提醒（除錯）
cd /d "%~dp0"
"%~dp0..\python\.venv\Scripts\python.exe" "%~dp0zhishen_alert_gui.pyw"
pause
