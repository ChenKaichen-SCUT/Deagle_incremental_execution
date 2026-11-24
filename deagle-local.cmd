@echo off
setlocal
wsl.exe --distribution Deagle-Jammy --user deagle --cd "%~dp0." --exec bash scripts/local/run.sh %*
exit /b %ERRORLEVEL%
