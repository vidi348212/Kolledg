#!/bin/bash

echo "========================================"
echo "Установка в автозагрузку (Linux)"
echo "========================================"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXE_NAME="student_monitor.py"
PYTHON_CMD="python3"

# Проверка наличия Python
if ! command -v python3 &> /dev/null; then
    echo "[ОШИБКА] Python3 не найден!"
    exit 1
fi

# Создание .desktop файла для автозагрузки
AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

cat > "$AUTOSTART_DIR/student_monitor.desktop" << DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=Student Monitor
Comment=Система мониторинга учеников
Exec=$PYTHON_CMD $SCRIPT_DIR/$EXE_NAME
Path=$SCRIPT_DIR
Terminal=false
X-GNOME-Autostart-enabled=true
DESKTOP_EOF

if [ $? -eq 0 ]; then
    chmod +x "$AUTOSTART_DIR/student_monitor.desktop"
    echo "[OK] Ярлык создан в автозагрузке!"
    echo "Путь: $AUTOSTART_DIR/student_monitor.desktop"
else
    echo "[ОШИБКА] Не удалось создать ярлык"
fi
