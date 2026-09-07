@echo off
chcp 65001 >nul
echo ========================================
echo Установка в автозагрузку
echo ========================================

set EXE_PATH=%~dp0dist\StudentMonitor.exe

if not exist "%EXE_PATH%" (
    echo [ОШИБКА] Файл StudentMonitor.exe не найден!
    echo Сначала создайте .exe через PyInstaller.
    pause
    exit /b
)

set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup

powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%STARTUP%\StudentMonitor.lnk'); $s.TargetPath = '%EXE_PATH%'; $s.WorkingDirectory = '%~dp0'; $s.Save()"

if %errorlevel% equ 0 (
    echo [OK] Ярлык создан в автозагрузке!
) else (
    echo [ОШИБКА] Не удалось создать ярлык
)

pause