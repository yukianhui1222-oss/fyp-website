@echo off
:: Use UTF-8 for compatibility
chcp 65001 >nul

echo.
echo ============================================================
echo  FYP OCR Document Parser - Auto Launcher
echo ============================================================
echo  Invoking Python 3.9 Environment...
echo.

:: Execute the test runner
"C:\Users\User\AppData\Local\Programs\Python\Python39\python.exe" "%~dp0fyp_test_runner.py"

echo.
echo Parsing process finished.
pause
