@echo off
chcp 65001 >nul
title 智伸科 4551 三層轉強提醒
cd /d "%~dp0"
set "PYTHONW=%~dp0..\python\.venv\Scripts\pythonw.exe"
if not exist "%PYTHONW%" (
  echo 找不到 Python 環境：%PYTHONW%
  echo 請先確認 python\.venv 已建立。
  pause
  exit /b 1
)
start "" "%PYTHONW%" "%~dp0zhishen_alert_gui.pyw"
