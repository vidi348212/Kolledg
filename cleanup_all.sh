#!/bin/bash

echo "========================================"
echo "Очистка временных файлов (Linux)"
echo "========================================"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Удаление логов
if [ -d "$SCRIPT_DIR/logs" ]; then
    echo "Удаление папки logs..."
    rm -rf "$SCRIPT_DIR/logs"
fi

# Удаление .pyc файлов
echo "Удаление .pyc файлов..."
find "$SCRIPT_DIR" -name "*.pyc" -delete
find "$SCRIPT_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null

# Удаление lock файла
rm -f "$SCRIPT_DIR/.student_monitor.lock"

echo "[OK] Очистка завершена!"
