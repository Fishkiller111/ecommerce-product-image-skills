@echo off
setlocal
set PYTHONUTF8=1
if defined PSB_PYTHON goto configured
py -3.12 "%~dp0scripts\render_sku.py" %*
exit /b %ERRORLEVEL%
:configured
"%PSB_PYTHON%" "%~dp0scripts\render_sku.py" %*
exit /b %ERRORLEVEL%
