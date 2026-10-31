@echo off
setlocal
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
"%~dp0.venv\Scripts\booth-auth.exe" %*
exit /b %ERRORLEVEL%
