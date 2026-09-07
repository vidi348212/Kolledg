@echo off
chcp 65001 >nul
echo ========================================
echo Создание задач в Планировщике
echo ========================================

set EXE_PATH=%~dp0dist\StudentMonitor.exe

:: Удаляем старые задачи
schtasks /delete /tn "StudentMonitor_Autostart" /f >nul 2>&1
schtasks /delete /tn "StudentMonitor_Daily" /f >nul 2>&1

:: Запуск при входе пользователя (не от системы!)
schtasks /create /tn "StudentMonitor_Autostart" ^
    /tr "\"%EXE_PATH%\"" ^
    /sc onlogon ^
    /rl LIMITED ^
    /f

:: Ежедневный запуск в 8:25
schtasks /create /tn "StudentMonitor_Daily" ^
    /tr "\"%EXE_PATH%\"" ^
    /sc daily ^
    /st 08:25 ^
    /rl LIMITED ^
    /f

if %errorlevel% equ 0 (
    echo [OK] Задачи созданы!
    echo Проверка: schtasks /query /tn StudentMonitor_Daily
) else (
    echo [ОШИБКА] Запустите от имени администратора
)

pause