@echo off
cd /d "%~dp0"
py demarrer.py pupitre
if errorlevel 9009 python demarrer.py pupitre
pause
