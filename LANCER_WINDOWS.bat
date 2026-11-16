@echo off
cd /d "%~dp0"
py demarrer.py
if errorlevel 1 python demarrer.py
pause
