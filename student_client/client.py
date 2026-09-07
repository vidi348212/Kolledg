"""
Клиентская часть системы мониторинга для компьютера ученика.
Запускается в фоновом режиме, слушает команды от учителя и выполняет их.
Включает функционал расписания, ввода имени и плашки из локальной версии.
"""
import sys
import os
import socket
import threading
import json
import time
import subprocess
import traceback
from datetime import datetime
from pathlib import Path

# Добавляем родительскую директорию в путь для импорта common
sys.path.insert(0, str(Path(__file__).parent.parent))

import psutil
try:
    import pygetwindow as gw
    GETWINDOW_AVAILABLE = True
except ImportError:
    GETWINDOW_AVAILABLE = False

from common.network_utils import (
    SERVER_HOST, SERVER_PORT, BROADCAST_PORT, DISCOVERY_MESSAGE, BUFFER_SIZE,
    STATUS_IDLE, STATUS_ACTIVE, STATUS_BLOCKED, STATUS_TEST_MODE,
    CMD_GET_STATUS, CMD_BLOCK_PC, CMD_UNBLOCK_PC, CMD_START_TEST, CMD_STOP_TEST,
    CMD_GET_SCREENSHOT, CMD_SHUTDOWN, CMD_RESTART, CMD_LOCK_SCREEN,
    CMD_GET_PROCESS_LIST, CMD_KILL_PROCESS, CMD_SEND_MESSAGE,
    get_local_ip, get_hostname, create_message, parse_message
)

# Windows-специфичные импорты
try:
    import ctypes
    import winsound
    from ctypes import wintypes
    WINDOWS_AVAILABLE = True
except ImportError:
    WINDOWS_AVAILABLE = False

# ============================================================
# ОПРЕДЕЛЕНИЕ ПАПКИ ПРОГРАММЫ И РАСПИСАНИЯ
# ============================================================

def get_app_directory():
    """Возвращает папку, где находится программа"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def find_schedule_file():
    """Ищет файл расписания в нескольких возможных местах"""
    app_dir = get_app_directory()
    
    possible_paths = [
        os.path.join(app_dir, "schedule.json"),
        os.path.join(app_dir, "..", "schedule.json"),
        os.path.join(os.getcwd(), "schedule.json"),
        os.path.join(app_dir, "..", "dist", "schedule.json"),
    ]
    
    for path in possible_paths:
        full_path = os.path.abspath(path)
        if os.path.exists(full_path):
            return full_path
    
    return os.path.join(app_dir, "schedule.json")


APP_DIR = get_app_directory()
SCHEDULE_FILE = find_schedule_file()
LOGS_DIR = Path(APP_DIR) / 'logs'
LOGS_DIR.mkdir(exist_ok=True)
DEBUG_LOG = LOGS_DIR / "debug.txt"


def debug_log(message):
    """Запись отладочной информации"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
        print(f"[{timestamp}] {message}")
    except Exception as e:
        print(f"Ошибка записи в лог: {e}")


# ============================================================
# МЕНЕДЖЕР РАСПИСАНИЯ
# ============================================================

class ScheduleManager:
    """Управление расписанием уроков"""
    
    def __init__(self, schedule_file=None):
        self.schedule_file = schedule_file or SCHEDULE_FILE
        self.last_modified = 0
        self.load_schedule()
        self.update_file_time()
    
    def update_file_time(self):
        try:
            if os.path.exists(self.schedule_file):
                self.last_modified = os.path.getmtime(self.schedule_file)
        except Exception:
            self.last_modified = 0
    
    def check_and_reload(self):
        try:
            if not os.path.exists(self.schedule_file):
                debug_log(f"[РАСПИСАНИЕ] Файл не найден: {self.schedule_file}")
                return False
            current_modified = os.path.getmtime(self.schedule_file)
            if current_modified != self.last_modified:
                debug_log(f"[РАСПИСАНИЕ] Файл изменён, перезагрузка...")
                self.load_schedule()
                self.update_file_time()
                return True
            return False
        except Exception as e:
            debug_log(f"[РАСПИСАНИЕ] Ошибка проверки: {e}")
            return False
    
    def load_schedule(self):
        try:
            debug_log(f"[РАСПИСАНИЕ] Загрузка: {self.schedule_file}")
            if os.path.exists(self.schedule_file):
                with open(self.schedule_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.lessons = data.get("lessons", [])
                    self.ask_every_lesson = data.get("ask_name_every_lesson", True)
                debug_log(f"[РАСПИСАНИЕ] Загружено уроков: {len(self.lessons)}")
            else:
                debug_log(f"[РАСПИСАНИЕ] Файл НЕ найден!")
                self.lessons = []
                self.ask_every_lesson = True
        except json.JSONDecodeError as e:
            debug_log(f"[РАСПИСАНИЕ] ОШИБКА ФОРМАТА JSON: {e}")
            self.lessons = []
            self.ask_every_lesson = True
        except Exception as e:
            debug_log(f"[РАСПИСАНИЕ] Ошибка: {e}")
            self.lessons = []
            self.ask_every_lesson = True
    
    def get_current_lesson(self):
        now = datetime.now().strftime("%H:%M")
        for lesson in self.lessons:
            if lesson["start"] <= now < lesson["end"]:
                return lesson
        return None
    
    def is_lesson_time(self):
        return self.get_current_lesson() is not None


# ============================================================
# ПЛАШКА С ИМЕНЕМ УЧЕНИКА (как в локальной версии)
# ============================================================

class NameOverlay:
    """Полупрозрачная плашка с именем ученика по центру вверху (стиль локальной версии)"""
    
    def __init__(self, student_name, lesson_number=None):
        self.student_name = student_name
        self.lesson_number = lesson_number
        self.root = None
        self.running = False
        self.thread = None
    
    def run(self):
        """Запуск плашки"""
        try:
            import tkinter as tk
            import tkinter.font as tkfont
            
            self.root = tk.Tk()
            self.root.title("Инфо об ученике")
            
            self.root.overrideredirect(True)
            self.root.attributes('-topmost', True)
            self.root.attributes('-alpha', 0.85)
            self.root.protocol("WM_DELETE_WINDOW", lambda: None)
            
            font = tkfont.Font(family="Arial", size=24, weight="bold")
            text_width = font.measure(self.student_name)
            
            padding = 40
            window_w = text_width + padding
            window_h = 60
            
            if window_w < 200:
                window_w = 200
            
            screen_w = self.root.winfo_screenwidth()
            x = (screen_w - window_w) // 2
            y = 20
            self.root.geometry(f"{window_w}x{window_h}+{x}+{y}")
            
            bg_color = "#2c3e50"
            self.root.configure(bg=bg_color)
            
            tk.Label(
                self.root,
                text=self.student_name,
                font=("Arial", 24, "bold"),
                fg="white",
                bg=bg_color
            ).pack(expand=True)
            
            def start_drag(event):
                self._drag_x = event.x
                self._drag_y = event.y
            
            def on_drag(event):
                x = self.root.winfo_x() + event.x - self._drag_x
                y = self.root.winfo_y() + event.y - self._drag_y
                self.root.geometry(f"+{x}+{y}")
            
            self.root.bind("<Button-1>", start_drag)
            self.root.bind("<B1-Motion>", on_drag)
            
            self.running = True
            self.root.mainloop()
            
        except Exception as e:
            debug_log(f"[ПЛАШКА] Ошибка: {e}")
    
    def start(self):
        """Запуск плашки в отдельном потоке"""
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        return self.thread
    
    def stop(self):
        """Остановка плашки"""
        self.running = False
        try:
            if self.root and self.root.winfo_exists():
                try:
                    self.root.quit()
                except:
                    pass
                try:
                    self.root.after(100, self.root.destroy)
                except:
                    self.root.destroy()
                
                # Ждем завершения потока (но не дольше 2 секунд)
                if self.thread and self.thread.is_alive():
                    self.thread.join(timeout=2.0)
        except Exception as e:
            debug_log(f"[ПЛАШКА] Ошибка при остановке: {e}")
        
        self.thread = None

class StudentClient:
    """Клиент для компьютера ученика с поддержкой расписания и ввода имени."""
    
    def __init__(self):
        self.student_name = ""
        self.server_address = None
        self.is_blocked = False
        self.is_test_mode = False
        self.block_window = None
        self.message_overlay = None
        self.name_overlay = None
        self.overlay_timer = None
        self.running = True
        self.socket_thread = None
        self.status = STATUS_IDLE
        self.current_lesson = None
        self.schedule_manager = ScheduleManager()
        self.start_time = time.time()
        
        # Путь для логирования
        self.log_dir = Path(__file__).parent / 'logs'
        self.log_dir.mkdir(exist_ok=True)
        self.log_file = self.log_dir / f"client_{datetime.now().strftime('%Y%m%d')}.log"
        
        self._log(f"Клиент запущен. Расписание: {SCHEDULE_FILE}")
        self._log(f"Уроков в расписании: {len(self.schedule_manager.lessons)}")
        
        # Запускаем главный цикл с расписанием
        self._run_schedule_loop()
    
    def _start_name_overlay(self):
        """Запуск плашки с именем студента."""
        try:
            if self.name_overlay:
                self.name_overlay.stop()
            lesson_num = self.current_lesson['lesson'] if self.current_lesson else None
            self.name_overlay = NameOverlay(self.student_name, lesson_num)
            self.name_overlay.start()
            self._log(f"Плашка с именем запущена: {self.student_name}")
        except Exception as e:
            self._log(f"Ошибка запуска плашки: {e}")
    
    def _stop_name_overlay(self):
        """Остановка плашки."""
        if self.name_overlay:
            self.name_overlay.stop()
            self.name_overlay = None
            self._log("Плашка остановлена")
    
    def _schedule_hide_overlay(self, minutes=5):
        """Запланировать скрытие плашки через N минут."""
        if self.overlay_timer:
            self.overlay_timer.cancel()
        
        def delayed_hide():
            self._stop_name_overlay()
            self.overlay_timer = None
        
        self.overlay_timer = threading.Timer(minutes * 60, delayed_hide)
        self.overlay_timer.daemon = True
        self.overlay_timer.start()
        self._log(f"Запланировано скрытие плашки через {minutes} минут")
    
    def _cancel_overlay_timer(self):
        """Отменить таймер скрытия плашки."""
        if self.overlay_timer:
            self.overlay_timer.cancel()
            self.overlay_timer = None
    
    def _log(self, message):
        """Логирование событий."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] {message}\n"
        print(log_entry.strip())
        
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception as e:
            print(f"Ошибка записи в лог: {e}")
    
    def _log_event(self, event_type, details):
        """Запись события в лог с информацией об уроке."""
        lesson_info = f"Урок {self.current_lesson['lesson']}" if self.current_lesson else "Вне урока"
        self._log(f"[{event_type}] {lesson_info}: {details}")
    
    def discover_server(self, timeout=5):
        """Поиск сервера учителя через широковещательную рассылку."""
        self._log("Поиск сервера учителя...")
        
        broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        broadcast_socket.settimeout(timeout)
        
        try:
            broadcast_socket.sendto(DISCOVERY_MESSAGE, ('<broadcast>', BROADCAST_PORT))
            data, addr = broadcast_socket.recvfrom(BUFFER_SIZE)
            
            if data == b'TEACHER_MONITOR_ACK':
                self.server_address = (addr[0], SERVER_PORT)
                self._log(f"Сервер найден: {self.server_address}")
                return True
        except socket.timeout:
            self._log("Сервер не найден. Работа в автономном режиме.")
        except Exception as e:
            self._log(f"Ошибка при поиске сервера: {e}")
        finally:
            broadcast_socket.close()
        
        return False
    
    def connect_to_server(self):
        """Подключение к серверу учителя."""
        if not self.server_address:
            return False
        
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.settimeout(10)
            self.client_socket.connect(self.server_address)
            self._log(f"Подключено к серверу {self.server_address}")
            return True
        except Exception as e:
            self._log(f"Ошибка подключения: {e}")
            return False
    
    def send_status(self):
        """Отправка текущего статуса учителю."""
        status_data = {
            'student_name': self.student_name,
            'hostname': get_hostname(),
            'ip_address': get_local_ip(),
            'status': self.status,
            'is_blocked': self.is_blocked,
            'is_test_mode': self.is_test_mode,
            'active_window': self.get_active_window_title(),
            'uptime': time.time() - self.start_time,
            'timestamp': datetime.now().isoformat()
        }
        
        message = create_message(CMD_GET_STATUS, status_data)
        try:
            self.client_socket.sendall(message)
            return True
        except Exception as e:
            self._log(f"Ошибка отправки статуса: {e}")
            return False
    
    def get_active_window_title(self):
        """Получение заголовка активного окна."""
        if not GETWINDOW_AVAILABLE:
            return "N/A"
        
        try:
            active_window = gw.getActiveWindow()
            return active_window.title if active_window else "No active window"
        except Exception:
            return "Error getting window title"
    
    def get_process_list(self):
        """Получение списка запущенных процессов."""
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'cpu': proc.info['cpu_percent'] or 0,
                    'memory': proc.info['memory_percent'] or 0
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        return processes[:50]  # Ограничим первыми 50 процессами
    
    def take_screenshot(self):
        """Сделать скриншот экрана."""
        try:
            from PIL import ImageGrab
            import base64
            import io
            
            screenshot = ImageGrab.grab()
            buffer = io.BytesIO()
            screenshot.save(buffer, format='PNG')
            screenshot_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            
            return {'screenshot': screenshot_base64, 'format': 'png'}
        except Exception as e:
            self._log(f"Ошибка создания скриншота: {e}")
            return {'error': str(e)}
    
    def block_pc(self, message="Компьютер заблокирован учителем"):
        """Блокировка компьютера ученика."""
        self._log(f"Блокировка ПК: {message}")
        self.is_blocked = True
        self.status = STATUS_BLOCKED
        
        if WINDOWS_AVAILABLE:
            # Показываем окно блокировки
            self._show_block_window(message)
    
    def _show_block_window(self, message):
        """Отображение окна блокировки (Windows)."""
        import tkinter as tk
        
        def create_window():
            self.block_window = tk.Tk()
            self.block_window.title("Заблокировано")
            self.block_window.attributes('-fullscreen', True)
            self.block_window.attributes('-topmost', True)
            
            screen_width = self.block_window.winfo_screenwidth()
            screen_height = self.block_window.winfo_screenheight()
            
            frame = tk.Frame(self.block_window, bg='#ff0000')
            frame.pack(fill='both', expand=True)
            
            label = tk.Label(
                frame,
                text=message,
                font=('Arial', 24, 'bold'),
                bg='#ff0000',
                fg='white',
                wraplength=screen_width - 100
            )
            label.place(relx=0.5, rely=0.5, anchor='center')
            
            sublabel = tk.Label(
                frame,
                text="Обратитесь к учителю для разблокировки",
                font=('Arial', 14),
                bg='#ff0000',
                fg='white'
            )
            sublabel.place(relx=0.5, rely=0.6, anchor='center')
            
            self.block_window.overrideredirect(True)
            self.block_window.mainloop()
        
        thread = threading.Thread(target=create_window, daemon=True)
        thread.start()
        self.block_window_thread = thread
    
    def unblock_pc(self):
        """Разблокировка компьютера."""
        self._log("Разблокировка ПК")
        self.is_blocked = False
        self.status = STATUS_IDLE
        
        if self.block_window:
            try:
                self.block_window.destroy()
            except:
                pass
            self.block_window = None
    
    def start_test_mode(self, config=None):
        """Включение режима контрольной работы."""
        self._log("Включение режима тестирования")
        self.is_test_mode = True
        self.status = STATUS_TEST_MODE
        
        # Здесь можно добавить ограничения на запуск программ
        if config:
            allowed_apps = config.get('allowed_apps', [])
            blocked_apps = config.get('blocked_apps', [])
            self._log(f"Разрешённые приложения: {allowed_apps}")
            self._log(f"Запрещённые приложения: {blocked_apps}")
    
    def stop_test_mode(self):
        """Выключение режима контрольной работы."""
        self._log("Выключение режима тестирования")
        self.is_test_mode = False
        self.status = STATUS_IDLE
    
    def kill_process(self, pid):
        """Завершение процесса по PID."""
        try:
            process = psutil.Process(pid)
            process.terminate()
            self._log(f"Процесс {pid} ({process.name()}) завершён")
            return {'success': True, 'message': f'Process {pid} terminated'}
        except Exception as e:
            self._log(f"Ошибка завершения процесса {pid}: {e}")
            return {'success': False, 'error': str(e)}
    
    def lock_screen(self):
        """Блокировка экрана (аналог Win+L)."""
        if WINDOWS_AVAILABLE:
            ctypes.windll.user32.LockWorkStation()
            self._log("Экран заблокирован")
            return {'success': True}
        return {'success': False, 'error': 'Lock screen available only on Windows'}
    
    def shutdown_pc(self):
        """Выключение компьютера."""
        self._log("Получена команда выключения")
        if WINDOWS_AVAILABLE:
            subprocess.call(['shutdown', '/s', '/t', '10'])
        else:
            subprocess.call(['shutdown', '-h', 'now'])
    
    def restart_pc(self):
        """Перезагрузка компьютера."""
        self._log("Получена команда перезагрузки")
        if WINDOWS_AVAILABLE:
            subprocess.call(['shutdown', '/r', '/t', '10'])
        else:
            subprocess.call(['shutdown', '-r', 'now'])
    
    def show_message(self, message):
        """Показать сообщение ученику."""
        self._log(f"Сообщение ученику: {message}")
        
        import tkinter as tk
        
        def create_overlay():
            self.message_overlay = tk.Tk()
            self.message_overlay.title("Сообщение от учителя")
            self.message_overlay.attributes('-topmost', True)
            
            screen_width = self.message_overlay.winfo_screenwidth()
            screen_height = self.message_overlay.winfo_screenheight()
            
            # Размеры окна
            width = 400
            height = 200
            x = (screen_width - width) // 2
            y = (screen_height - height) // 2
            
            self.message_overlay.geometry(f"{width}x{height}+{x}+{y}")
            
            label = tk.Label(
                self.message_overlay,
                text=message,
                font=('Arial', 14),
                wraplength=380,
                justify='center'
            )
            label.pack(expand=True)
            
            btn = tk.Button(
                self.message_overlay,
                text="OK",
                command=self.message_overlay.destroy
            )
            btn.pack(pady=10)
            
            self.message_overlay.mainloop()
        
        thread = threading.Thread(target=create_overlay, daemon=True)
        thread.start()
    
    def handle_command(self, command_data):
        """Обработка команды от учителя."""
        command = command_data.get('command')
        data = command_data.get('data', {})
        
        self._log(f"Получена команда: {command}")
        
        response = {'command': command, 'success': False}
        
        try:
            if command == CMD_GET_STATUS:
                self.send_status()
                return
            
            elif command == CMD_BLOCK_PC:
                self.block_pc(data.get('message', 'Компьютер заблокирован'))
                response['success'] = True
            
            elif command == CMD_UNBLOCK_PC:
                self.unblock_pc()
                response['success'] = True
            
            elif command == CMD_START_TEST:
                self.start_test_mode(data)
                response['success'] = True
            
            elif command == CMD_STOP_TEST:
                self.stop_test_mode()
                response['success'] = True
            
            elif command == CMD_GET_SCREENSHOT:
                screenshot_data = self.take_screenshot()
                response.update(screenshot_data)
                response['success'] = 'error' not in screenshot_data
            
            elif command == CMD_GET_PROCESS_LIST:
                processes = self.get_process_list()
                response['processes'] = processes
                response['success'] = True
            
            elif command == CMD_KILL_PROCESS:
                result = self.kill_process(data.get('pid'))
                response.update(result)
            
            elif command == CMD_LOCK_SCREEN:
                result = self.lock_screen()
                response.update(result)
            
            elif command == CMD_SHUTDOWN:
                self.shutdown_pc()
                response['success'] = True
            
            elif command == CMD_RESTART:
                self.restart_pc()
                response['success'] = True
            
            elif command == CMD_SEND_MESSAGE:
                self.show_message(data.get('message', ''))
                response['success'] = True
            
            else:
                response['error'] = f'Неизвестная команда: {command}'
        
        except Exception as e:
            response['error'] = str(e)
            self._log(f"Ошибка выполнения команды {command}: {e}")
        
        # Отправка ответа
        try:
            response_message = create_message(command, response)
            self.client_socket.sendall(response_message)
        except Exception as e:
            self._log(f"Ошибка отправки ответа: {e}")
    
    def listen_for_commands(self):
        """Прослушивание команд от сервера."""
        while self.running:
            try:
                data = self.client_socket.recv(BUFFER_SIZE)
                if not data:
                    self._log("Соединение разорвано")
                    break
                
                command_data = parse_message(data)
                if 'error' not in command_data:
                    self.handle_command(command_data)
                else:
                    self._log(f"Ошибка в команде: {command_data['error']}")
            
            except socket.timeout:
                continue
            except Exception as e:
                self._log(f"Ошибка при получении данных: {e}")
                time.sleep(1)
        
        self.running = False
    
    def heartbeat(self):
        """Периодическая отправка статуса (heartbeat)."""
        while self.running:
            try:
                if self.server_address and hasattr(self, 'client_socket'):
                    self.send_status()
            except Exception as e:
                self._log(f"Ошибка heartbeat: {e}")
            
            time.sleep(30)  # Отправка каждые 30 секунд
    
    def run(self):
        """Основной цикл работы клиента."""
        self.start_time = time.time()
        self._log("=" * 50)
        self._log("Студент клиент запущен")
        
        # Поиск сервера
        if not self.discover_server():
            self._log("Сервер не найден. Повторим поиск через 60 секунд...")
        
        # Попытка подключения
        if self.server_address:
            if self.connect_to_server():
                # Запуск потоков
                self.socket_thread = threading.Thread(target=self.listen_for_commands, daemon=True)
                self.socket_thread.start()
                
                heartbeat_thread = threading.Thread(target=self.heartbeat, daemon=True)
                heartbeat_thread.start()
                
                self._log("Клиент работает в обычном режиме")
            else:
                self._log("Не удалось подключиться к серверу")
        else:
            self._log("Работа в автономном режиме (без сервера)")
        
        # Основной цикл
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self._log("Получен сигнал остановки")
        finally:
            self.stop()
    
    def stop(self):
        """Остановка клиента."""
        self._log("Остановка клиента...")
        self.running = False
        
        # Останавливаем плашку с именем
        if self.name_overlay:
            try:
                self.name_overlay.stop()
            except Exception as e:
                self._log(f"Ошибка остановки плашки: {e}")
            self.name_overlay = None
        
        if hasattr(self, 'client_socket'):
            try:
                self.client_socket.close()
            except:
                pass
        
        self.unblock_pc()
        self._log("Клиент остановлен")


def main():
    """Точка входа для клиента."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Student Monitor Client')
    parser.add_argument('--name', type=str, help='Имя студента')
    parser.add_argument('--auto', action='store_true', help='Автоматический запуск при старте системы')
    
    args = parser.parse_args()
    
    client = StudentClient(student_name=args.name)
    
    try:
        client.run()
    except Exception as e:
        print(f"Критическая ошибка: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
