@echo off
cd /d "%~dp0"
py demarrer.py lab
if errorlevel 9009 python demarrer.py lab
pause
