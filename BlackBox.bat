@echo off
chcp 65001 >nul
title War Thunder BlackBox
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python bulunamadi. https://www.python.org adresinden kurup "Add to PATH" secenegini isaretle.
  pause
  exit /b 1
)
echo War Thunder BlackBox baslatiliyor...
echo Kaydedici + pano izleyici + otomatik ice aktarma + arayuz. Kapatmak icin bu pencerede Ctrl+C.
echo.
python -m blackbox start
if errorlevel 1 pause
