import tkinter as tk
from tkinter import simpledialog, messagebox
import tkinter.font as tkfont
import psutil
import time
import threading
import os
import sys
import json
import ctypes
from datetime import datetime
import winsound
import traceback

from extended_monitoring import (
    FileMonitor, BrowserTracker, InstallGuard, load_settings
)


# ============================================================
# ОПРЕДЕЛЕНИЕ ПАПКИ ПРОГРАММЫ
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
LOGS_DIR = os.path.join(APP_DIR, "logs")
DEBUG_LOG = os.path.join(LOGS_DIR, "debug.txt")


def debug_log(message):
    """Запись отладочной информации"""
    try:
        if not os.path.exists(LOGS_DIR):
            os.makedirs(LOGS_DIR)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
        print(f"[{timestamp}] {message}")
    except Exception as e:
        print(f"Ошибка записи в лог: {e}")


# ============================================================
# ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК
# ============================================================

def global_exception_handler(exc_type, exc_value, exc_traceback):
    """Ловит все необработанные исключения"""
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    debug_log(f"[КРИТИЧЕСКАЯ ОШИБКА] {error_msg}")
    
    try:
        with open(os.path.join(LOGS_DIR, "errors.txt"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now()}]\n{error_msg}\n")
    except:
        pass


sys.excepthook = global_exception_handler


# ============================================================
# ЗАЩИТА ОТ ДВОЙНОГО ЗАПУСКА
# ============================================================

class SingleInstance:
    """Проверяет, запущена ли уже программа"""
    
    def __init__(self, mutex_name="StudentMonitor_SingleInstance"):
        self.mutex_name = mutex_name
        self.mutex = None
    
    def is_already_running(self):
        """Возвращает True если программа уже запущена"""
        try:
            self.mutex = ctypes.windll.kernel32.CreateMutexW(
                None, False, self.mutex_name
            )
            last_error = ctypes.windll.kernel32.GetLastError()
            return last_error == 183
        except Exception as e:
            debug_log(f"[ЗАЩИТА] Ошибка проверки: {e}")
            return False
    
    def release(self):
        """Освободить мьютекс при выходе"""
        try:
            if self.mutex:
                ctypes.windll.kernel32.CloseHandle(self.mutex)
        except:
            pass


# ============================================================
# ФИЛЬТР ПРОЦЕССОВ
# ============================================================

SYSTEM_PROCESSES = {
    'system', 'system idle process', 'registry', 'memory compression',
    'smss.exe', 'csrss.exe', 'wininit.exe', 'winlogon.exe',
    'services.exe', 'lsass.exe', 'svchost.exe', 'spoolsv.exe',
    'dwm.exe', 'explorer.exe', 'taskhostw.exe', 'sihost.exe',
    'runtimebroker.exe', 'fontdrvhost.exe', 'wudfhost.exe',
    'conhost.exe', 'ctfmon.exe', 'searchindexer.exe',
    'wlanext.exe', 'lsm.exe', 'audiodg.exe', 'dllhost.exe',
    'msmpeng.exe', 'niservice.exe', 'defender.exe',
    'shellexperiencehost.exe', 'startmenuexperiencehost.exe',
    'textinputhost.exe', 'applicationframehost.exe',
    'searchapp.exe', 'searchui.exe', 'searchprotocolhost.exe',
    'searchfilterhost.exe', 'widgets.exe', 'smartscreen.exe',
    'igfxtray.exe', 'igfxpers.exe', 'hkcmd.exe',
    'nvvsvc.exe', 'nvcontainer.exe', 'radeonsoftware.exe',
    'tiworker.exe', 'trustedinstaller.exe',
    'compattelrunner.exe', 'telemetry.exe',
    'python.exe', 'pythonw.exe', 'cmd.exe', 'powershell.exe',
    'tasklist.exe', 'taskkill.exe',
}

SYSTEM_USERS = [
    'nt authority\\system',
    'nt authority\\local service',
    'nt authority\\network service',
    'window manager\\',
    'font driver host\\',
    'iotadmin\\',
    'desktop window manager\\',
]


def is_system_process(proc):
    """Проверяет, является ли процесс системным"""
    try:
        name = proc.info.get('name', '').lower()
        if name in SYSTEM_PROCESSES:
            return True
        try:
            username = proc.username().lower()
            for sys_user in SYSTEM_USERS:
                if username.startswith(sys_user):
                    return True
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass
        return False
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return True


def is_installer_process(proc_name):
    """Проверяет, похож ли процесс на установщик"""
    installer_keywords = ['setup', 'install', 'installer', 'msiexec',
                          'uninstall', 'update', 'updater', 'patch']
    name_lower = proc_name.lower()
    return any(keyword in name_lower for keyword in installer_keywords)


# ============================================================
# ПЛАШКА С ИМЕНЕМ УЧЕНИКА НА ЭКРАНЕ
# ============================================================

class NameOverlay:
    """Полупрозрачная плашка с именем ученика по центру вверху"""
    
    def __init__(self, student_name, lesson_number=None):
        self.student_name = student_name
        self.lesson_number = lesson_number
        self.root = None
        self.running = False
    
    def run(self):
        """Запуск плашки"""
        try:
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
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        return thread
    
    def stop(self):
        """Остановка плашки"""
        self.running = False
        try:
            if self.root and self.root.winfo_exists():
                self.root.quit()
                self.root.destroy()
        except:
            pass


# ============================================================
# РАСПИСАНИЕ УРОКОВ
# ============================================================

class ScheduleManager:
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
# ОСНОВНАЯ ПРОГРАММА
# ============================================================

class StudentMonitor:
    def __init__(self):
        self.student_name = ""
        self.schedule_manager = ScheduleManager()
        self.monitoring = False
        self.current_lesson = None
        self.name_overlay = None
        self.overlay_timer = None
        
        # Загрузка расширенных настроек
        settings_path = os.path.join(APP_DIR, "settings.json")
        self.settings = load_settings(settings_path)
        
        # Инициализация расширенных модулей
        self.file_monitor = None
        self.browser_tracker = None
        self.install_guard = None
        
        self.baseline_processes = self.get_user_processes()
        debug_log(f"[СТАТИСТИКА] При старте процессов: {len(self.baseline_processes)}")
        
        if not os.path.exists(LOGS_DIR):
            os.makedirs(LOGS_DIR)
        self.log_file = os.path.join(
            LOGS_DIR,
            f"student_log_{datetime.now().strftime('%Y%m%d')}.txt"
        )
        
        # Инициализация расширенного мониторинга
        self.init_extended_monitoring()
    
    def init_extended_monitoring(self):
        """Инициализация расширенного мониторинга"""
        
        # 1. Мониторинг файлов
        file_settings = self.settings.get("file_monitoring", {})
        if file_settings.get("enabled", False):
            self.file_monitor = FileMonitor(
                file_settings,
                self.log_event,
                lambda: self.student_name
            )
            self.file_monitor.start()
            debug_log(f"[РАСШИРЕНИЕ] Мониторинг файлов запущен")
        
        # 2. Мониторинг браузеров
        browser_settings = self.settings.get("browser_monitoring", {})
        if browser_settings.get("enabled", False):
            browsers = browser_settings.get("browsers", [])
            interval = browser_settings.get("check_interval_seconds", 5)
            self.browser_tracker = BrowserTracker(
                browsers,
                self.log_event,
                interval
            )
            self.browser_tracker.start()
            debug_log(f"[РАСШИРЕНИЕ] Мониторинг браузеров запущен")
        
        # 3. Защита от установок
        install_settings = self.settings.get("install_guard", {})
        if install_settings.get("enabled", False):
            password = self.settings.get("teacher_password", "12345")
            keywords = install_settings.get("installer_keywords", [])
            self.install_guard = InstallGuard(
                password,
                keywords,
                self.log_event,
                self.ask_teacher_password
            )
            self.install_guard.start()
            debug_log(f"[РАСШИРЕНИЕ] Защита от установок запущена")
    
    def ask_teacher_password(self, installer_name):
        """Запрос пароля учителя для разрешения установки"""
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            
            password = simpledialog.askstring(
                "Требуется разрешение учителя",
                f"Обнаружена установка программы:\n{installer_name}\n\n"
                f"Введите пароль учителя для разрешения:",
                show='*',
                parent=root
            )
            
            root.destroy()
            return password or ""
        except Exception as e:
            debug_log(f"[ПАРОЛЬ] Ошибка запроса пароля: {e}")
            return ""
    
    def get_user_processes(self):
        """Получить список НЕсистемных процессов"""
        processes = set()
        for proc in psutil.process_iter(['pid', 'name', 'exe', 'create_time']):
            try:
                if not is_system_process(proc):
                    proc_key = (
                        proc.info['pid'],
                        proc.info['name'],
                        proc.info.get('exe', '') or '',
                        proc.info.get('create_time', 0)
                    )
                    processes.add(proc_key)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return processes
    
    def log_event(self, event_type, details):
        """Запись события в лог"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lesson_info = f"Урок {self.current_lesson['lesson']}" if self.current_lesson else "Вне урока"
        log_entry = f"[{timestamp}] [{lesson_info}] Ученик: {self.student_name} | {event_type}: {details}\n"
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_entry)
            print(log_entry.strip())
        except Exception as e:
            debug_log(f"[ЛОГ] Ошибка записи: {e}")
    
    # ===== Управление плашкой =====
    
    def show_name_overlay(self):
        """Показать плашку с именем ученика"""
        self.hide_name_overlay()
        
        if self.student_name:
            lesson_num = self.current_lesson['lesson'] if self.current_lesson else None
            self.name_overlay = NameOverlay(self.student_name, lesson_num)
            self.name_overlay.start()
            debug_log(f"[ПЛАШКА] Показана плашка с именем: {self.student_name}")
    
    def hide_name_overlay(self):
        """Скрыть плашку с именем ученика"""
        if hasattr(self, 'name_overlay') and self.name_overlay:
            self.name_overlay.stop()
            self.name_overlay = None
            debug_log(f"[ПЛАШКА] Плашка скрыта")
    
    def schedule_hide_overlay(self, minutes=5):
        """Запланировать скрытие плашки через N минут"""
        if self.overlay_timer:
            self.overlay_timer.cancel()
            self.overlay_timer = None
        
        def delayed_hide():
            self.hide_name_overlay()
            self.overlay_timer = None
        
        self.overlay_timer = threading.Timer(minutes * 60, delayed_hide)
        self.overlay_timer.daemon = True
        self.overlay_timer.start()
        debug_log(f"[ПЛАШКА] Запланировано скрытие через {minutes} минут")
    
    def cancel_overlay_timer(self):
        """Отменить запланированное скрытие плашки"""
        if self.overlay_timer:
            self.overlay_timer.cancel()
            self.overlay_timer = None
            debug_log(f"[ПЛАШКА] Таймер скрытия отменён")
    
    # ===== Мониторинг процессов =====
    
    def monitor_processes(self):
        """Мониторинг процессов в фоновом потоке"""
        while self.monitoring:
            try:
                current_processes = self.get_user_processes()
                current_by_name = {(p[1], p[2], p[3]) for p in current_processes}
                baseline_by_name = {(p[1], p[2], p[3]) for p in self.baseline_processes}
                new_processes = current_by_name - baseline_by_name
                
                for proc_name, proc_path, create_time in new_processes:
                    if create_time > self.start_time:
                        event_type = "УСТАНОВКА" if is_installer_process(proc_name) else "ЗАПУСК"
                        self.log_event(event_type, f"{proc_name} ({proc_path})")
                
                # Проверка защиты от установок
                if self.install_guard:
                    self.install_guard.check_new_installers(new_processes)
                
                self.baseline_processes = current_processes
            except Exception as e:
                debug_log(f"[МОНИТОРИНГ] Ошибка: {e}")
            time.sleep(5)
    
    # ===== Окно ввода имени =====
    
    def get_student_name(self):
        """Полноэкранное окно ввода имени с автозакрытием в конце урока"""
        debug_log(f"[ОКНО] Показ окна ввода имени")
        
        result = {"name": None, "timeout": False}
        
        try:
            root = tk.Tk()
            root.title("Идентификация ученика")
            root.attributes('-fullscreen', True)
            root.attributes('-topmost', True)
            root.configure(bg="#2c3e50")
            
            def block_close():
                pass
            
            root.protocol("WM_DELETE_WINDOW", block_close)
            root.bind("<Alt-F4>", lambda e: None)
            
            screen_h = root.winfo_screenheight()
            
            tk.Label(
                root,
                text="КАБИНЕТ ИНФОРМАТИКИ",
                font=("Arial", 48, "bold"),
                fg="white", bg="#2c3e50"
            ).pack(pady=(screen_h // 8, 20))
            
            lesson_text = f"Урок №{self.current_lesson['lesson']}" if self.current_lesson else ""
            tk.Label(
                root,
                text=lesson_text,
                font=("Arial", 36),
                fg="#f1c40f", bg="#2c3e50"
            ).pack(pady=(0, 40))
            
            tk.Label(
                root,
                text="Введите вашу фамилию и имя:",
                font=("Arial", 32),
                fg="#ecf0f1", bg="#2c3e50"
            ).pack(pady=(0, 30))
            
            entry = tk.Entry(
                root,
                font=("Arial", 40),
                width=30,
                justify="center",
                bd=3, relief="solid"
            )
            entry.pack(ipady=15)
            entry.focus_set()
            
            def on_submit(event=None):
                name = entry.get().strip()
                if name:
                    result["name"] = name
                    root.quit()
                    root.destroy()
                else:
                    entry.config(bg="#ffcccc")
                    root.after(500, lambda: entry.config(bg="white"))
            
            entry.bind("<Return>", on_submit)
            
            tk.Button(
                root,
                text="ПОДТВЕРДИТЬ",
                font=("Arial", 28, "bold"),
                bg="#27ae60", fg="white",
                activebackground="#2ecc71",
                activeforeground="white",
                width=20, height=2, bd=0,
                cursor="hand2",
                command=on_submit
            ).pack(pady=40)
            
            countdown_label = tk.Label(
                root,
                text="",
                font=("Arial", 20),
                fg="#e74c3c", bg="#2c3e50"
            )
            countdown_label.pack(pady=10)
            
            tk.Label(
                root,
                text="Нажмите Enter или кнопку ПОДТВЕРДИТЬ",
                font=("Arial", 18),
                fg="#7f8c8d", bg="#2c3e50"
            ).pack(side="bottom", pady=40)
            
            time_label = tk.Label(
                root,
                text=datetime.now().strftime("%H:%M:%S"),
                font=("Arial", 24),
                fg="#95a5a6", bg="#2c3e50"
            )
            time_label.pack(side="bottom", pady=10)
            
            seconds_left = None
            if self.current_lesson:
                now = datetime.now()
                end_h, end_m = map(int, self.current_lesson['end'].split(':'))
                end_time = now.replace(hour=end_h, minute=end_m, second=0)
                seconds_left = int((end_time - now).total_seconds())
                
                if seconds_left < 0:
                    seconds_left = 0
            
            def update_countdown():
                nonlocal seconds_left
                try:
                    if root.winfo_exists() and seconds_left is not None:
                        if seconds_left > 0:
                            minutes = seconds_left // 60
                            secs = seconds_left % 60
                            countdown_label.config(
                                text=f"До конца урока: {minutes:02d}:{secs:02d}"
                            )
                            seconds_left -= 1
                            root.after(1000, update_countdown)
                        else:
                            countdown_label.config(text="Урок закончился!")
                except:
                    pass
            
            def update_time():
                try:
                    if root.winfo_exists():
                        time_label.config(text=datetime.now().strftime("%H:%M:%S"))
                        root.after(1000, update_time)
                except:
                    pass
            
            def auto_close():
                result["timeout"] = True
                debug_log(f"[ОКНО] Автоматическое закрытие - конец урока")
                try:
                    root.quit()
                    root.destroy()
                except:
                    pass
            
            if seconds_left is not None and seconds_left > 0:
                root.after(seconds_left * 1000, auto_close)
                update_countdown()
            elif seconds_left is not None and seconds_left <= 0:
                root.after(1000, auto_close)
            
            update_time()
            root.update()
            root.lift()
            root.focus_force()
            entry.focus_set()
            
            debug_log(f"[ОКНО] Окно создано, ожидание ввода")
            
            root.mainloop()
            
            try:
                root.destroy()
            except:
                pass
            
            if result["timeout"]:
                self.log_event("ОКНО", "Окно закрыто автоматически - имя не введено")
                debug_log(f"[ОКНО] Окно закрыто по таймауту")
                return False
            
            if result["name"]:
                self.student_name = result["name"]
                self.log_event("ВХОД", "Ученик сел за компьютер")
                self.show_name_overlay()
                return True
            
            return False
            
        except Exception as e:
            debug_log(f"[ОКНО] Ошибка: {e}")
            debug_log(f"[ОКНО] Трассировка: {traceback.format_exc()}")
            return False
    
    # ===== Главный цикл =====
    
    def run(self):
        """Главный цикл программы"""
        self.start_time = time.time()
        
        debug_log("=" * 50)
        debug_log("СИСТЕМА МОНИТОРИНГА УЧЕНИКОВ")
        debug_log("=" * 50)
        debug_log(f"Папка программы: {APP_DIR}")
        debug_log(f"Файл расписания: {SCHEDULE_FILE}")
        debug_log(f"Файл существует: {os.path.exists(SCHEDULE_FILE)}")
        debug_log(f"Время запуска: {datetime.now().strftime('%H:%M:%S')}")
        debug_log(f"Уроков в расписании: {len(self.schedule_manager.lessons)}")
        debug_log(f"Сейчас идёт урок: {'Да' if self.schedule_manager.is_lesson_time() else 'Нет'}")
        debug_log("=" * 50)
        
        self.monitoring = True
        monitor_thread = threading.Thread(target=self.monitor_processes, daemon=True)
        monitor_thread.start()
        
        last_asked_lesson = None
        last_schedule_check = 0
        
        current = self.schedule_manager.get_current_lesson()
        if current:
            debug_log(f"[СТАРТ] Обнаружен текущий урок: {current['lesson']}")
            self.current_lesson = current
            self.get_student_name()
            last_asked_lesson = current
        else:
            debug_log(f"[СТАРТ] Сейчас нет урока")
        
        while True:
            try:
                current_time = time.time()
                if current_time - last_schedule_check >= 20:
                    last_schedule_check = current_time
                    if self.schedule_manager.check_and_reload():
                        self.log_event("РАСПИСАНИЕ", "Файл расписания был обновлён")
                        last_asked_lesson = None
                        current = self.schedule_manager.get_current_lesson()
                        if current:
                            self.current_lesson = current
                            self.student_name = ""
                            self.get_student_name()
                            last_asked_lesson = current
                
                lesson = self.schedule_manager.get_current_lesson()
                
                if lesson and lesson != last_asked_lesson:
                    debug_log(f"[УРОК] Обнаружен новый урок: {lesson['lesson']}")
                    self.current_lesson = lesson
                    
                    try:
                        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                    except:
                        pass
                    
                    self.log_event("НАЧАЛО УРОКА", f"Урок №{lesson['lesson']}")
                    
                    if self.schedule_manager.ask_every_lesson:
                        self.student_name = ""
                        self.cancel_overlay_timer()
                        self.hide_name_overlay()
                        self.log_event("ЗАПРОС ИМЕНИ", f"Ожидание ввода для урока №{lesson['lesson']}")
                        self.get_student_name()
                    else:
                        if not self.student_name:
                            self.get_student_name()
                        else:
                            self.log_event("СМЕНА УРОКА", f"Переход к уроку №{lesson['lesson']}")
                            self.show_name_overlay()
                    
                    last_asked_lesson = lesson
                
                elif not lesson and last_asked_lesson is not None:
                    debug_log(f"[УРОК] Урок {last_asked_lesson['lesson']} закончился")
                    self.log_event("КОНЕЦ УРОКА", f"Урок №{last_asked_lesson['lesson']} завершён")
                    self.current_lesson = None
                    last_asked_lesson = None
                    
                    self.schedule_hide_overlay(minutes=5)
                    
                    if self.student_name:
                        self.log_event("ВЫХОД", "Ученик завершил работу (конец урока)")
                        self.student_name = ""
                
                time.sleep(5)
                
            except KeyboardInterrupt:
                self.monitoring = False
                
                if self.file_monitor:
                    self.file_monitor.stop()
                if self.browser_tracker:
                    self.browser_tracker.stop()
                if self.install_guard:
                    self.install_guard.stop()
                
                self.cancel_overlay_timer()
                self.hide_name_overlay()
                self.log_event("ВЫХОД", "Программа остановлена")
                break
            except Exception as e:
                debug_log(f"[ГЛАВНЫЙ ЦИКЛ] Ошибка: {e}")
                debug_log(f"[ГЛАВНЫЙ ЦИКЛ] Трассировка: {traceback.format_exc()}")
                time.sleep(5)


# ============================================================
# ТОЧКА ВХОДА
# ============================================================

if __name__ == "__main__":
    instance_check = SingleInstance()
    
    if instance_check.is_already_running():
        debug_log("[ЗАЩИТА] Программа уже запущена, повторный запуск отменён")
        
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning(
                "Программа уже запущена",
                "Система мониторинга уже работает.\nПовторный запуск не требуется."
            )
            root.destroy()
        except:
            pass
        
        sys.exit(0)
    
    debug_log("[ЗАПУСК] Программа стартовала (первый экземпляр)")
    
    try:
        if "--test" in sys.argv:
            print("[ТЕСТ] Запуск в тестовом режиме...")
            monitor = StudentMonitor()
            monitor.current_lesson = {"lesson": 0, "start": "00:00", "end": "23:59"}
            monitor.get_student_name()
            print(f"[ТЕСТ] Введено имя: {monitor.student_name}")
            time.sleep(30)
        else:
            monitor = StudentMonitor()
            monitor.run()
    except Exception as e:
        debug_log(f"[КРИТИЧЕСКАЯ ОШИБКА] {e}")
        debug_log(f"[КРИТИЧЕСКАЯ ОШИБКА] Трассировка: {traceback.format_exc()}")
    finally:
        instance_check.release()