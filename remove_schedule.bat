@echo off
chcp 65001 >nul
echo ========================================
echo Удаление задач StudentMonitor
echo ========================================

schtasks /delete /tn "StudentMonitor_Autostart" /f >nul 2>&1
schtasks /delete /tn "StudentMonitor_Daily" /f >nul 2>&1

set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
del "%STARTUP%\StudentMonitor.lnk" /f /q >nul 2>&1

echo [OK] Все задачи удалены!
pause