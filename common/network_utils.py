"""
Общие утилиты и константы для системы мониторинга класса.
"""
import socket
import json
import hashlib
import time
from datetime import datetime

# Конфигурация сети
SERVER_HOST = '0.0.0.0'  # Слушать все интерфейсы
SERVER_PORT = 54321
BROADCAST_PORT = 54322
DISCOVERY_MESSAGE = b'STUDENT_MONITOR_DISCOVERY'
BUFFER_SIZE = 4096

# Статусы студента
STATUS_IDLE = 'idle'
STATUS_ACTIVE = 'active'
STATUS_BLOCKED = 'blocked'
STATUS_TEST_MODE = 'test_mode'

# Команды сервера
CMD_GET_STATUS = 'get_status'
CMD_BLOCK_PC = 'block_pc'
CMD_UNBLOCK_PC = 'unblock_pc'
CMD_START_TEST = 'start_test'
CMD_STOP_TEST = 'stop_test'
CMD_GET_SCREENSHOT = 'get_screenshot'
CMD_SHUTDOWN = 'shutdown'
CMD_RESTART = 'restart'
CMD_LOCK_SCREEN = 'lock_screen'
CMD_GET_PROCESS_LIST = 'get_process_list'
CMD_KILL_PROCESS = 'kill_process'
CMD_SEND_MESSAGE = 'send_message'

def get_local_ip():
    """Получить локальный IP-адрес компьютера."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

def get_hostname():
    """Получить имя хоста."""
    return socket.gethostname()

def create_message(command, data=None):
    """Создать сообщение в формате JSON для передачи по сети."""
    message = {
        'command': command,
        'timestamp': datetime.now().isoformat(),
        'data': data or {}
    }
    return json.dumps(message).encode('utf-8')

def parse_message(raw_data):
    """Разобрать полученное сообщение."""
    try:
        data = json.loads(raw_data.decode('utf-8'))
        return data
    except Exception as e:
        return {'error': str(e)}

def hash_password(password):
    """Хеширование пароля."""
    return hashlib.sha256(password.encode()).hexdigest()

def generate_session_id():
    """Генерация уникального ID сессии."""
    return f"{int(time.time())}_{hashlib.md5(str(time.time()).encode()).hexdigest()[:8]}"
