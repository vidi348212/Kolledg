@echo off
REM Запуск клиента ученика в фоновом режиме
REM Для автозагрузки добавьте этот файл в автозагрузку Windows

cd /d "%~dp0"
start "" python student_client\client.py --auto
echo Клиент запущен
