@echo off
cd /d "%~dp0"
python soundboard.py
if errorlevel 1 (
    echo.
    echo Soundboard exited with an error. Read the message above.
    pause
)
