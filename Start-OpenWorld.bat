@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-OpenWorld.ps1" %*
set "OPENWORLD_EXIT=%errorlevel%"
if not "%OPENWORLD_EXIT%"=="0" (
  echo.
  echo OpenWorld could not start. See the error above.
  pause
)
endlocal & exit /b %OPENWORLD_EXIT%
