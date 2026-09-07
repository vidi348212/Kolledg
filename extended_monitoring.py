"""
Расширенный мониторинг:
- Отслеживание работы с файлами на всех дисках
- Отслеживание посещаемых сайтов
- Защита от установки программ
"""

import os
import time
import threading
import psutil
import json
import string
from datetime import datetime
from pathlib import Path

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    FileSystemEventHandler = object

try:
    import pygetwindow as gw
    PYGETWINDOW_AVAILABLE = True
except ImportError:
    PYGETWINDOW_AVAILABLE = False


# ============================================================
# ЗАГРУЗКА НАСТРОЕК
# ============================================================

def load_settings(settings_file="settings.json"):
    """Загрузка настроек из файла"""
    default_settings = {
        "teacher_password": "12345",
        "file_monitoring": {
            "enabled": False,
            "monitor_all_drives": False,
            "folders": [],
            "excluded_folders": [],
            "excluded_extensions": []
        },
        "browser_monitoring": {
            "enabled": False,
            "browsers": [],
            "check_interval_seconds": 5
        },
        "install_guard": {
            "enabled": False,
            "installer_keywords": []
        }
    }
    
    try:
        if os.path.exists(settings_file):
            with open(settings_file, "r", encoding="utf-8") as f:
                settings = json.load(f)
                return {**default_settings, **settings}
    except Exception as e:
        print(f"Ошибка загрузки настроек: {e}")
    
    return default_settings


# ============================================================
# МОНИТОРИНГ ФАЙЛОВ НА ВСЕХ ДИСКАХ
# ============================================================

class FileMonitorHandler(FileSystemEventHandler):
    """Обработчик событий файловой системы с фильтрацией"""
    
    def __init__(self, log_callback, student_name_getter, 
                 excluded_folders=None, excluded_extensions=None):
        if WATCHDOG_AVAILABLE:
            super().__init__()
        self.log_callback = log_callback
        self.get_student_name = student_name_getter
        self.excluded_folders = excluded_folders or []
        self.excluded_extensions = excluded_extensions or []
        
        # Нормализуем пути исключений
        self.excluded_folders = [
            os.path.normpath(p).lower() for p in self.excluded_folders
        ]
    
    def should_ignore(self, path):
        """Проверяет, нужно ли игнорировать файл/папку"""
        if not path:
            return True
        
        path_lower = path.lower()
        normalized = os.path.normpath(path_lower)
        
        # Исключение по папкам
        for excluded in self.excluded_folders:
            if normalized.startswith(excluded):
                return True
        
        # Исключение по расширению
        _, ext = os.path.splitext(path_lower)
        if ext in self.excluded_extensions:
            return True
        
        return False
    
    def on_created(self, event):
        if not event.is_directory and not self.should_ignore(event.src_path):
            self.log_callback("ФАЙЛ СОЗДАН", event.src_path)
    
    def on_deleted(self, event):
        if not event.is_directory and not self.should_ignore(event.src_path):
            self.log_callback("ФАЙЛ УДАЛЁН", event.src_path)
    
    def on_moved(self, event):
        if not event.is_directory:
            if not self.should_ignore(event.src_path) or not self.should_ignore(event.dest_path):
                self.log_callback(
                    "ФАЙЛ ПЕРЕИМЕНОВАН",
                    f"{event.src_path} → {event.dest_path}"
                )


class FileMonitor:
    """Мониторинг файловых операций на всех дисках или в указанных папках"""
    
    def __init__(self, settings, log_callback, student_name_getter):
        self.settings = settings
        self.log_callback = log_callback
        self.get_student_name = student_name_getter
        self.observer = None
        self.running = False
        
        # Стандартные исключения для уменьшения шума
        self.default_excluded_folders = [
            os.path.join(os.environ.get('SystemRoot', 'C:\\Windows')).lower(),
            os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files')).lower(),
            os.path.join(os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)')).lower(),
            os.path.join(os.environ.get('ProgramData', 'C:\\ProgramData')).lower(),
            os.path.join(str(Path.home()), 'AppData').lower(),
            os.path.join(str(Path.home()), 'NTUSER.DAT').lower(),
        ]
        
        # Стандартные исключения по расширениям (временные файлы)
        self.default_excluded_extensions = {
            '.tmp', '.temp', '.log', '.part', '.crdownload',
            '.lock', '.pid', '.seed', '.dmp', '.old',
            '.cache', '.swp', '.bak',
        }
    
    def get_all_drives(self):
        """Получить список всех доступных дисков"""
        drives = []
        
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            try:
                if os.path.exists(drive):
                    os.listdir(drive)
                    drives.append(drive)
            except (PermissionError, OSError):
                continue
        
        return drives
    
    def get_user_folder(self, folder_name):
        """Получить путь к пользовательской папке"""
        user_home = Path.home()
        
        folder_map = {
            "Desktop": user_home / "Desktop",
            "Documents": user_home / "Documents",
            "Downloads": user_home / "Downloads",
            "Pictures": user_home / "Pictures",
            "Music": user_home / "Music",
            "Videos": user_home / "Videos",
        }
        
        # Если передан прямой путь (например "D:\\StudentWork")
        if os.path.isabs(folder_name) or ':\\' in folder_name:
            return Path(folder_name)
        
        return folder_map.get(folder_name, user_home / folder_name)
    
    def get_excluded_folders(self):
        """Получить полный список исключений"""
        excluded = self.default_excluded_folders.copy()
        
        user_excluded = self.settings.get("excluded_folders", [])
        for folder in user_excluded:
            excluded.append(os.path.normpath(folder).lower())
        
        return excluded
    
    def get_excluded_extensions(self):
        """Получить список исключённых расширений"""
        excluded = self.default_excluded_extensions.copy()
        
        user_excluded = self.settings.get("excluded_extensions", [])
        for ext in user_excluded:
            if not ext.startswith('.'):
                ext = '.' + ext
            excluded.add(ext.lower())
        
        return excluded
    
    def start(self):
        """Запуск мониторинга"""
        if not WATCHDOG_AVAILABLE:
            print("[ФАЙЛЫ] Библиотека watchdog не установлена")
            return
        
        try:
            self.observer = Observer()
            
            handler = FileMonitorHandler(
                self.log_callback,
                self.get_student_name,
                self.get_excluded_folders(),
                self.get_excluded_extensions()
            )
            
            monitored_paths = []
            
            # Режим мониторинга всех дисков
            if self.settings.get("monitor_all_drives", False):
                drives = self.get_all_drives()
                print(f"[ФАЙЛЫ] Обнаружено дисков: {len(drives)}")
                
                for drive in drives:
                    monitored_paths.append(drive)
                    print(f"[ФАЙЛЫ] Мониторинг диска: {drive}")
            else:
                # Мониторинг только указанных папок
                folders = self.settings.get("folders", [])
                for folder_name in folders:
                    folder_path = self.get_user_folder(folder_name)
                    if folder_path.exists():
                        monitored_paths.append(str(folder_path))
                        print(f"[ФАЙЛЫ] Мониторинг папки: {folder_path}")
            
            # Запускаем наблюдение
            for path in monitored_paths:
                try:
                    self.observer.schedule(handler, path, recursive=True)
                except Exception as e:
                    print(f"[ФАЙЛЫ] Не удалось наблюдать {path}: {e}")
            
            self.observer.start()
            self.running = True
            print(f"[ФАЙЛЫ] Мониторинг запущен для {len(monitored_paths)} путей")
            
        except Exception as e:
            print(f"[ФАЙЛЫ] Ошибка запуска: {e}")
    
    def stop(self):
        """Остановка мониторинга"""
        if self.observer and self.running:
            try:
                self.observer.stop()
                self.observer.join()
                self.running = False
                print("[ФАЙЛЫ] Мониторинг остановлен")
            except Exception as e:
                print(f"[ФАЙЛЫ] Ошибка остановки: {e}")


# ============================================================
# МОНИТОРИНГ БРАУЗЕРОВ (посещаемые сайты)
# ============================================================

class BrowserTracker:
    """Отслеживание посещаемых сайтов через заголовки окон"""
    
    def __init__(self, browsers, log_callback, check_interval=5):
        self.browsers = [b.lower() for b in browsers]
        self.log_callback = log_callback
        self.check_interval = check_interval
        self.running = False
        self.last_title = ""
    
    def get_active_window_info(self):
        """Получить информацию об активном окне"""
        if not PYGETWINDOW_AVAILABLE:
            return None, None
        
        try:
            active_window = gw.getActiveWindow()
            if active_window:
                title = active_window.title
                process_name = self.get_active_process()
                return process_name, title
        except Exception:
            pass
        
        return None, None
    
    def get_active_process(self):
        """Получить имя активного процесса браузера"""
        try:
            for proc in psutil.process_iter(['name']):
                try:
                    proc_name = proc.info['name'].lower()
                    if proc_name in self.browsers:
                        return proc_name
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except:
            pass
        return None
    
    def parse_site_from_title(self, title):
        """Извлечь название сайта из заголовка окна"""
        if not title:
            return None
        
        separators = [' - ', ' — ', ' | ']
        
        for sep in separators:
            if sep in title:
                parts = title.split(sep)
                return parts[0].strip()
        
        return title
    
    def monitor_loop(self):
        """Основной цикл мониторинга"""
        while self.running:
            try:
                process_name, title = self.get_active_window_info()
                
                if process_name and process_name in self.browsers:
                    if title and title != self.last_title:
                        site_name = self.parse_site_from_title(title)
                        if site_name:
                            self.log_callback("САЙТ", f"{site_name} ({process_name})")
                            self.last_title = title
                
                time.sleep(self.check_interval)
                
            except Exception as e:
                print(f"[БРАУЗЕР] Ошибка: {e}")
                time.sleep(self.check_interval)
    
    def start(self):
        """Запуск мониторинга в отдельном потоке"""
        if not PYGETWINDOW_AVAILABLE:
            print("[БРАУЗЕР] Библиотека pygetwindow не установлена")
            return
        
        self.running = True
        thread = threading.Thread(target=self.monitor_loop, daemon=True)
        thread.start()
    
    def stop(self):
        """Остановка мониторинга"""
        self.running = False


# ============================================================
# ЗАЩИТА ОТ УСТАНОВКИ ПРОГРАММ
# ============================================================

class InstallGuard:
    """Контроль установки программ с паролем учителя"""
    
    def __init__(self, password, installer_keywords, log_callback, ask_password_callback):
        self.password = password
        self.installer_keywords = [k.lower() for k in installer_keywords]
        self.log_callback = log_callback
        self.ask_password = ask_password_callback
        self.running = False
        self.allowed_installers = set()
    
    def is_installer(self, process_name):
        """Проверяет, является ли процесс установщиком"""
        name_lower = process_name.lower()
        return any(keyword in name_lower for keyword in self.installer_keywords)
    
    def check_new_installers(self, current_processes):
        """Проверяет новые процессы на предмет установщиков"""
        if not self.running:
            return
        
        for proc_name, proc_path, create_time in current_processes:
            proc_key = (proc_name, create_time)
            
            if proc_key in self.allowed_installers:
                continue
            
            if self.is_installer(proc_name):
                self.handle_installer(proc_name, proc_path, proc_key)
    
    def handle_installer(self, proc_name, proc_path, proc_key):
        """Обработка обнаруженного установщика"""
        self.log_callback("УСТАНОВКА ОБНАРУЖЕНА", f"{proc_name} ({proc_path})")
        
        password = self.ask_password(proc_name)
        
        if password == self.password:
            self.allowed_installers.add(proc_key)
            self.log_callback("УСТАНОВКА РАЗРЕШЕНА", f"{proc_name} - пароль учителя введён")
        else:
            self.log_callback("УСТАНОВКА ЗАБЛОКИРОВАНА", f"{proc_name} - пароль не введён")
            self.kill_installer(proc_name)
    
    def kill_installer(self, proc_name):
        """Завершить процесс установщика"""
        try:
            for proc in psutil.process_iter(['name', 'pid']):
                try:
                    if proc.info['name'].lower() == proc_name.lower():
                        proc.terminate()
                        try:
                            proc.wait(timeout=3)
                        except psutil.TimeoutExpired:
                            proc.kill()
                        self.log_callback(
                            "ПРОЦЕСС ЗАВЕРШЁН",
                            f"{proc_name} (PID: {proc.info['pid']})"
                        )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            print(f"[ЗАЩИТА] Ошибка завершения процесса: {e}")
    
    def start(self):
        """Запуск защиты"""
        self.running = True
    
    def stop(self):
        """Остановка защиты"""
        self.running = False