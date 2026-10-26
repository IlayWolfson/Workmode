@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m focus_guard.update --apply
pause
