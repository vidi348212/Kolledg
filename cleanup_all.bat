@echo off
chcp 65001 >nul
echo ========================================
echo Полная очистка автозапусков
echo ========================================

schtasks /delete /tn "StudentMonitor_Autostart" /f >nul 2>&1
schtasks /delete /tn "StudentMonitor_Daily" /f >nul 2>&1

set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
del "%STARTUP%\StudentMonitor.lnk" /f /q >nul 2>&1
del "%STARTUP%\StudentMonitor.exe" /f /q >nul 2>&1

reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "StudentMonitor" /f >nul 2>&1
reg delete "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v "StudentMonitor" /f >nul 2>&1

echo [OK] Все автозапуски удалены!
pause