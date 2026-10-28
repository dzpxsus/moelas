@echo off
TITLE JESUS Gnu alarm Launcher
cd /d "%~dp0"

echo Checking and installing required packages (Pillow, sounddevice, soundfile, pynput, numpy)...
pip install pillow sounddevice soundfile pynput numpy >nul 2>&1

echo Starting JESUS Gnu alarm...
python soundboard.py
pause
