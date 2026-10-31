@echo off
setlocal
rem Keep output UTF-8 safe (the CLI prints emoji, which crashes on cp932 pipes)
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
rem Store data next to the repo so the command works from any directory
set "BOOTH_ITEMS_DIR=%~dp0BoothItems"
set "BOOTH_DOWNLOADS_DIR=%~dp0BoothDownloads"
"%~dp0.venv\Scripts\booth-assets-manager.exe" %*
exit /b %ERRORLEVEL%
