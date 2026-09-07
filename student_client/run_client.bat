@echo off
REM Запуск клиента ученика с диалогом ввода имени
REM Для автозагрузки добавьте этот файл в автозагрузку Windows

cd /d "%~dp0"
start "" python student_client\client.py --auto
echo Клиент запущен. Введите имя студента в появившемся окне.
