@echo off
setlocal
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
"%~dp0.venv\Scripts\booth-assets-manager.exe" %*
exit /b %ERRORLEVEL%
