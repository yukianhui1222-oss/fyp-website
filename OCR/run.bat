@echo off
chcp 65001 >nul
title OCR 文档解析引擎

echo.
echo  ==========================================
echo   OCR 文档解析引擎 — 启动中...
echo  ==========================================
echo.

C:\Users\User\AppData\Local\Programs\Python\Python39\python.exe "%~dp0test_runner.py"

echo.
pause
