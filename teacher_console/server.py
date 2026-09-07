"""
Серверная часть системы мониторинга для компьютера учителя.
Управляет подключенными клиентами (компьютерами учеников),
отображает их статус и отправляет команды.
"""
import sys
import socket
import threading
import json
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime
from pathlib import Path

# Добавляем родительскую директорию в путь для импорта common
sys.path.insert(0, str(Path(__file__).parent.parent))

from common.network_utils import (
    SERVER_HOST, SERVER_PORT, BROADCAST_PORT, DISCOVERY_MESSAGE, BUFFER_SIZE,
    STATUS_IDLE, STATUS_ACTIVE, STATUS_BLOCKED, STATUS_TEST_MODE,
    CMD_GET_STATUS, CMD_BLOCK_PC, CMD_UNBLOCK_PC, CMD_START_TEST, CMD_STOP_TEST,
    CMD_GET_SCREENSHOT, CMD_SHUTDOWN, CMD_RESTART, CMD_LOCK_SCREEN,
    CMD_GET_PROCESS_LIST, CMD_KILL_PROCESS, CMD_SEND_MESSAGE,
    get_local_ip, get_hostname, create_message, parse_message
)


class TeacherServer:
    """Сервер для управления компьютерами учеников."""
    
    def __init__(self):
        self.students = {}  # {ip_address: student_info}
        self.server_socket = None
        self.broadcast_socket = None
        self.running = False
        self.client_threads = {}
        
        # Путь для логирования
        self.log_dir = Path(__file__).parent / 'logs'
        self.log_dir.mkdir(exist_ok=True)
        self.log_file = self.log_dir / f"server_{datetime.now().strftime('%Y%m%d')}.log"
        
        self._log("Сервер учителя инициализирован")
    
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
    
    def start_broadcast_listener(self):
        """Запуск прослушивания широковещательных запросов от клиентов."""
        self.broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.broadcast_socket.bind(('', BROADCAST_PORT))
        self.broadcast_socket.settimeout(1)
        
        self._log(f"Слушаем широковещательные запросы на порту {BROADCAST_PORT}")
        
        def listen():
            while self.running:
                try:
                    data, addr = self.broadcast_socket.recvfrom(BUFFER_SIZE)
                    if data == DISCOVERY_MESSAGE:
                        self._log(f"Обнаружен клиент: {addr[0]}")
                        self.broadcast_socket.sendto(b'TEACHER_MONITOR_ACK', addr)
                        self._log(f"Отправлен ответ клиенту {addr[0]}")
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self._log(f"Ошибка broadcast: {e}")
                    break
        
        thread = threading.Thread(target=listen, daemon=True)
        thread.start()
        return thread
    
    def start_server(self):
        """Запуск TCP сервера для приёма соединений от клиентов."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((SERVER_HOST, SERVER_PORT))
        self.server_socket.listen(50)  # До 50 одновременных подключений
        self.server_socket.settimeout(1)
        
        self._log(f"Сервер запущен на {SERVER_HOST}:{SERVER_PORT}")
        
        def accept_connections():
            while self.running:
                try:
                    client_socket, addr = self.server_socket.accept()
                    self._log(f"Подключён клиент: {addr}")
                    
                    # Запуск потока для обработки клиента
                    thread = threading.Thread(
                        target=self.handle_client,
                        args=(client_socket, addr),
                        daemon=True
                    )
                    thread.start()
                    self.client_threads[addr[0]] = thread
                    
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self._log(f"Ошибка приёма соединения: {e}")
                    break
        
        thread = threading.Thread(target=accept_connections, daemon=True)
        thread.start()
        return thread
    
    def handle_client(self, client_socket, addr):
        """Обработка подключённого клиента."""
        ip = addr[0]
        
        try:
            while self.running:
                data = client_socket.recv(BUFFER_SIZE)
                if not data:
                    break
                
                message = parse_message(data)
                
                if 'command' in message:
                    command = message['command']
                    command_data = message.get('data', {})
                    
                    if command == CMD_GET_STATUS:
                        # Обновление информации о студенте
                        self.students[ip] = {
                            'ip': ip,
                            'student_name': command_data.get('student_name', 'Unknown'),
                            'hostname': command_data.get('hostname', 'Unknown'),
                            'status': command_data.get('status', STATUS_IDLE),
                            'is_blocked': command_data.get('is_blocked', False),
                            'is_test_mode': command_data.get('is_test_mode', False),
                            'active_window': command_data.get('active_window', 'N/A'),
                            'last_seen': datetime.now(),
                            'uptime': command_data.get('uptime', 0),
                            'socket': client_socket
                        }
                        self._log(f"Статус от {ip}: {command_data.get('student_name')} - {command_data.get('status')}")
                    
                    # Обработка других команд с ответом может быть добавлена здесь
        
        except Exception as e:
            self._log(f"Ошибка обработки клиента {ip}: {e}")
        finally:
            if ip in self.students:
                del self.students[ip]
            self._log(f"Клиент {ip} отключился")
            
            try:
                client_socket.close()
            except:
                pass
    
    def send_command(self, ip, command, data=None):
        """Отправка команды конкретному клиенту."""
        if ip not in self.students:
            return {'success': False, 'error': 'Client not found'}
        
        student = self.students[ip]
        socket = student.get('socket')
        
        if not socket:
            return {'success': False, 'error': 'No socket connection'}
        
        try:
            message = create_message(command, data)
            socket.sendall(message)
            self._log(f"Команда {command} отправлена {ip}")
            return {'success': True}
        except Exception as e:
            self._log(f"Ошибка отправки команды {ip}: {e}")
            return {'success': False, 'error': str(e)}
    
    def send_command_to_all(self, command, data=None):
        """Отправка команды всем подключенным клиентам."""
        results = {}
        for ip in list(self.students.keys()):
            results[ip] = self.send_command(ip, command, data)
        return results
    
    def stop(self):
        """Остановка сервера."""
        self._log("Остановка сервера...")
        self.running = False
        
        # Закрытие всех соединений
        for student in list(self.students.values()):
            try:
                if 'socket' in student and student['socket']:
                    student['socket'].close()
            except:
                pass
        
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        
        if self.broadcast_socket:
            try:
                self.broadcast_socket.close()
            except:
                pass
        
        self._log("Сервер остановлен")


class TeacherGUI:
    """Графический интерфейс для учителя."""
    
    def __init__(self, server):
        self.server = server
        self.root = tk.Tk()
        self.root.title("Мониторинг класса - Компьютер учителя")
        self.root.geometry("1200x700")
        
        self.selected_student_ip = None
        
        self._setup_ui()
        self._start_auto_refresh()
    
    def _setup_ui(self):
        """Настройка пользовательского интерфейса."""
        # Верхняя панель
        top_frame = tk.Frame(self.root, bg='#2c3e50', height=60)
        top_frame.pack(fill='x')
        top_frame.pack_propagate(False)
        
        title_label = tk.Label(
            top_frame,
            text="📚 Мониторинг класса",
            font=('Arial', 18, 'bold'),
            bg='#2c3e50',
            fg='white'
        )
        title_label.pack(pady=15)
        
        # Основная область
        main_paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill='both', expand=True)
        
        # Левая панель - список студентов
        left_frame = tk.Frame(main_paned, width=400)
        main_paned.add(left_frame)
        
        # Заголовок списка
        list_header = tk.Frame(left_frame, bg='#ecf0f1', height=40)
        list_header.pack(fill='x')
        list_header.pack_propagate(False)
        
        tk.Label(
            list_header,
            text="Ученики в сети",
            font=('Arial', 12, 'bold'),
            bg='#ecf0f1'
        ).pack(pady=10)
        
        # Дерево студентов
        columns = ('name', 'status', 'window')
        self.student_tree = ttk.Treeview(left_frame, columns=columns, show='headings')
        
        self.student_tree.heading('name', text='Имя')
        self.student_tree.heading('status', text='Статус')
        self.student_tree.heading('window', text='Активное окно')
        
        self.student_tree.column('name', width=150)
        self.student_tree.column('status', width=100)
        self.student_tree.column('window', width=130)
        
        scrollbar = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.student_tree.yview)
        self.student_tree.configure(yscrollcommand=scrollbar.set)
        
        self.student_tree.pack(side=tk.LEFT, fill='both', expand=True)
        scrollbar.pack(side=tk.RIGHT, fill='y')
        
        self.student_tree.bind('<<TreeviewSelect>>', self._on_student_select)
        
        # Правая панель - управление
        right_frame = tk.Frame(main_paned)
        main_paned.add(right_frame)
        
        # Информация о выбранном студенте
        info_frame = tk.LabelFrame(right_frame, text="Информация", padx=10, pady=10)
        info_frame.pack(fill='x', padx=10, pady=5)
        
        self.info_labels = {}
        for i, field in enumerate(['student_name', 'ip', 'hostname', 'status', 'active_window', 'uptime']):
            label = tk.Label(info_frame, text=f"{field}: ", anchor='w', font=('Arial', 10))
            label.grid(row=i, column=0, sticky='w', pady=2)
            value_label = tk.Label(info_frame, text="-", anchor='w', font=('Arial', 10, 'bold'))
            value_label.grid(row=i, column=1, sticky='w', pady=2, padx=5)
            self.info_labels[field] = value_label
        
        # Панель действий
        actions_frame = tk.LabelFrame(right_frame, text="Действия", padx=10, pady=10)
        actions_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        # Кнопки управления
        btn_style = {'width': 25, 'pady': 8}
        
        tk.Button(
            actions_frame,
            text="🖥️ Заблокировать компьютер",
            command=self._block_pc,
            bg='#e74c3c',
            fg='white',
            **btn_style
        ).pack(pady=5)
        
        tk.Button(
            actions_frame,
            text="✅ Разблокировать компьютер",
            command=self._unblock_pc,
            bg='#27ae60',
            fg='white',
            **btn_style
        ).pack(pady=5)
        
        tk.Button(
            actions_frame,
            text="📝 Начать контрольную работу",
            command=self._start_test,
            bg='#3498db',
            fg='white',
            **btn_style
        ).pack(pady=5)
        
        tk.Button(
            actions_frame,
            text="⏹️ Завершить контрольную работу",
            command=self._stop_test,
            bg='#95a5a6',
            fg='white',
            **btn_style
        ).pack(pady=5)
        
        tk.Button(
            actions_frame,
            text="📸 Получить скриншот",
            command=self._get_screenshot,
            **btn_style
        ).pack(pady=5)
        
        tk.Button(
            actions_frame,
            text="💬 Отправить сообщение",
            command=self._send_message,
            **btn_style
        ).pack(pady=5)
        
        tk.Button(
            actions_frame,
            text="🔒 Заблокировать экран (Win+L)",
            command=self._lock_screen,
            **btn_style
        ).pack(pady=5)
        
        # Опасные действия
        danger_frame = tk.LabelFrame(right_frame, text="Опасные действия", padx=10, pady=10, fg='red')
        danger_frame.pack(fill='x', padx=10, pady=5)
        
        tk.Button(
            danger_frame,
            text="⚠️ Выключить компьютер ученика",
            command=self._shutdown_pc,
            bg='#c0392b',
            fg='white',
            **btn_style
        ).pack(pady=5)
        
        tk.Button(
            danger_frame,
            text="🔄 Перезагрузить компьютер ученика",
            command=self._restart_pc,
            bg='#e67e22',
            fg='white',
            **btn_style
        ).pack(pady=5)
        
        # Действия для всех
        all_frame = tk.LabelFrame(right_frame, text="Действия для всех", padx=10, pady=10)
        all_frame.pack(fill='x', padx=10, pady=5)
        
        tk.Button(
            all_frame,
            text="📢 Отправить сообщение всем",
            command=self._send_message_all,
            width=25,
            pady=8
        ).pack(pady=5)
        
        tk.Button(
            all_frame,
            text="📝 Начать тест для всех",
            command=self._start_test_all,
            width=25,
            pady=8,
            bg='#3498db',
            fg='white'
        ).pack(pady=5)
        
        # Лог событий
        log_frame = tk.LabelFrame(right_frame, text="Журнал событий", padx=5, pady=5)
        log_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, font=('Consolas', 9))
        self.log_text.pack(fill='both', expand=True)
        
        # Статус бар
        self.status_var = tk.StringVar()
        self.status_var.set("Готов")
        status_bar = tk.Label(
            self.root,
            textvariable=self.status_var,
            bd=1,
            relief=tk.SUNKEN,
            anchor=tk.W
        )
        status_bar.pack(side=tk.BOTTOM, fill='x')
    
    def _on_student_select(self, event):
        """Обработка выбора студента."""
        selection = self.student_tree.selection()
        if not selection:
            return
        
        item = self.student_tree.item(selection[0])
        name = item['values'][0]
        
        # Поиск IP по имени
        for ip, student in self.server.students.items():
            if student.get('student_name') == name:
                self.selected_student_ip = ip
                self._update_info_panel(student)
                break
    
    def _update_info_panel(self, student):
        """Обновление информационной панели."""
        fields = {
            'student_name': student.get('student_name', 'N/A'),
            'ip': student.get('ip', 'N/A'),
            'hostname': student.get('hostname', 'N/A'),
            'status': student.get('status', 'N/A'),
            'active_window': student.get('active_window', 'N/A'),
            'uptime': f"{student.get('uptime', 0):.0f} сек"
        }
        
        for field, value in fields.items():
            self.info_labels[field].config(text=str(value))
    
    def _refresh_student_list(self):
        """Обновление списка студентов."""
        # Очистка текущего списка
        for item in self.student_tree.get_children():
            self.student_tree.delete(item)
        
        # Добавление студентов
        for ip, student in self.server.students.items():
            status_emoji = {
                STATUS_IDLE: '🟢',
                STATUS_ACTIVE: '🟡',
                STATUS_BLOCKED: '🔴',
                STATUS_TEST_MODE: '📝'
            }.get(student.get('status'), '⚪')
            
            self.student_tree.insert('', 'end', values=(
                student.get('student_name', 'Unknown'),
                f"{status_emoji} {student.get('status', 'unknown')}",
                student.get('active_window', 'N/A')[:30]
            ))
        
        count = len(self.server.students)
        self.status_var.set(f"Подключено учеников: {count}")
        self._log_gui(f"Список обновлён. Всего: {count}")
    
    def _log_gui(self, message):
        """Запись в GUI лог."""
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
    
    def _start_auto_refresh(self):
        """Автообновление списка каждые 5 секунд."""
        def refresh():
            self._refresh_student_list()
            self.root.after(5000, refresh)
        
        refresh()
    
    # Методы действий
    def _check_selection(self):
        """Проверка выбора студента."""
        if not self.selected_student_ip:
            messagebox.showwarning("Предупреждение", "Выберите ученика из списка")
            return False
        return True
    
    def _block_pc(self):
        """Заблокировать компьютер."""
        if not self._check_selection():
            return
        
        message = messagebox.askstring(
            "Блокировка",
            "Введите сообщение для ученика:",
            initialvalue="Компьютер заблокирован учителем"
        )
        
        if message:
            result = self.server.send_command(
                self.selected_student_ip,
                CMD_BLOCK_PC,
                {'message': message}
            )
            
            if result.get('success'):
                self._log_gui(f"✅ Компьютер заблокирован")
                messagebox.showinfo("Успех", "Компьютер ученика заблокирован")
            else:
                messagebox.showerror("Ошибка", result.get('error', 'Неизвестная ошибка'))
    
    def _unblock_pc(self):
        """Разблокировать компьютер."""
        if not self._check_selection():
            return
        
        result = self.server.send_command(self.selected_student_ip, CMD_UNBLOCK_PC)
        
        if result.get('success'):
            self._log_gui(f"✅ Компьютер разблокирован")
            messagebox.showinfo("Успех", "Компьютер ученика разблокирован")
        else:
            messagebox.showerror("Ошибка", result.get('error', 'Неизвестная ошибка'))
    
    def _start_test(self):
        """Начать контрольную работу."""
        if not self._check_selection():
            return
        
        config = {}
        
        # Можно добавить диалог настройки теста
        result = self.server.send_command(
            self.selected_student_ip,
            CMD_START_TEST,
            config
        )
        
        if result.get('success'):
            self._log_gui(f"📝 Тест начат")
            messagebox.showinfo("Успех", "Режим контрольной работы включён")
        else:
            messagebox.showerror("Ошибка", result.get('error', 'Неизвестная ошибка'))
    
    def _stop_test(self):
        """Завершить контрольную работу."""
        if not self._check_selection():
            return
        
        result = self.server.send_command(self.selected_student_ip, CMD_STOP_TEST)
        
        if result.get('success'):
            self._log_gui(f"⏹️ Тест завершён")
            messagebox.showinfo("Успех", "Режим контрольной работы выключен")
        else:
            messagebox.showerror("Ошибка", result.get('error', 'Неизвестная ошибка'))
    
    def _get_screenshot(self):
        """Получить скриншот."""
        if not self._check_selection():
            return
        
        self._log_gui(f"📸 Запрос скриншота...")
        result = self.server.send_command(self.selected_student_ip, CMD_GET_SCREENSHOT)
        
        if result.get('success'):
            self._log_gui(f"✅ Скриншот получен")
            # Здесь можно добавить отображение скриншота
            messagebox.showinfo("Успех", "Скриншот получен (функционал просмотра будет добавлен)")
        else:
            messagebox.showerror("Ошибка", result.get('error', 'Неизвестная ошибка'))
    
    def _send_message(self):
        """Отправить сообщение."""
        if not self._check_selection():
            return
        
        message = messagebox.askstring(
            "Сообщение",
            "Введите сообщение для ученика:"
        )
        
        if message:
            result = self.server.send_command(
                self.selected_student_ip,
                CMD_SEND_MESSAGE,
                {'message': message}
            )
            
            if result.get('success'):
                self._log_gui(f"💬 Сообщение отправлено: {message}")
                messagebox.showinfo("Успех", "Сообщение отправлено")
            else:
                messagebox.showerror("Ошибка", result.get('error', 'Неизвестная ошибка'))
    
    def _lock_screen(self):
        """Заблокировать экран."""
        if not self._check_selection():
            return
        
        if messagebox.askyesno("Подтверждение", "Заблокировать экран ученика?"):
            result = self.server.send_command(self.selected_student_ip, CMD_LOCK_SCREEN)
            
            if result.get('success'):
                self._log_gui(f"🔒 Экран заблокирован")
                messagebox.showinfo("Успех", "Экран ученика заблокирован")
            else:
                messagebox.showerror("Ошибка", result.get('error', 'Неизвестная ошибка'))
    
    def _shutdown_pc(self):
        """Выключить компьютер."""
        if not self._check_selection():
            return
        
        if messagebox.askyesno("⚠️ Внимание", "Вы уверены, что хотите выключить компьютер ученика?"):
            result = self.server.send_command(self.selected_student_ip, CMD_SHUTDOWN)
            
            if result.get('success'):
                self._log_gui(f"⚠️ Отправлена команда выключения")
                messagebox.showinfo("Успех", "Команда выключения отправлена")
            else:
                messagebox.showerror("Ошибка", result.get('error', 'Неизвестная ошибка'))
    
    def _restart_pc(self):
        """Перезагрузить компьютер."""
        if not self._check_selection():
            return
        
        if messagebox.askyesno("⚠️ Внимание", "Вы уверены, что хотите перезагрузить компьютер ученика?"):
            result = self.server.send_command(self.selected_student_ip, CMD_RESTART)
            
            if result.get('success'):
                self._log_gui(f"🔄 Отправлена команда перезагрузки")
                messagebox.showinfo("Успех", "Команда перезагрузки отправлена")
            else:
                messagebox.showerror("Ошибка", result.get('error', 'Неизвестная ошибка'))
    
    def _send_message_all(self):
        """Отправить сообщение всем."""
        message = messagebox.askstring(
            "Сообщение всем",
            "Введите сообщение для всех учеников:"
        )
        
        if message:
            results = self.server.send_command_to_all(CMD_SEND_MESSAGE, {'message': message})
            success_count = sum(1 for r in results.values() if r.get('success'))
            self._log_gui(f"💬 Сообщение отправлено {success_count}/{len(results)} ученикам")
            messagebox.showinfo("Результат", f"Сообщение отправлено {success_count} из {len(results)} учеников")
    
    def _start_test_all(self):
        """Начать тест для всех."""
        if messagebox.askyesno("Подтверждение", "Начать контрольную работу для всех учеников?"):
            results = self.server.send_command_to_all(CMD_START_TEST, {})
            success_count = sum(1 for r in results.values() if r.get('success'))
            self._log_gui(f"📝 Тест начат для {success_count}/{len(results)} учеников")
            messagebox.showinfo("Результат", f"Тест начат для {success_count} из {len(results)} учеников")
    
    def run(self):
        """Запуск GUI."""
        self._log_gui("Интерфейс учителя запущен")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()
    
    def _on_close(self):
        """Закрытие приложения."""
        if messagebox.askyesno("Выход", "Остановить сервер и выйти?"):
            self.server.stop()
            self.root.destroy()


def main():
    """Точка входа для сервера учителя."""
    server = TeacherServer()
    server.running = True
    
    # Запуск сервера
    server.start_broadcast_listener()
    server.start_server()
    
    # Запуск GUI
    gui = TeacherGUI(server)
    gui.run()


if __name__ == '__main__':
    main()
