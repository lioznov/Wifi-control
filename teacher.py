import queue
import socket as sc
import threading
import json
from ipaddress import ip_address
import hashlib
import hmac
import secrets
from tkinter import messagebox, ttk
from wsgiref.util import request_uri

import customtkinter as ctk

ctk.set_appearance_mode("dark")

student_events = queue.Queue()
server_events = queue.Queue()
SERVER_PORT = 47473
presence_events = queue.Queue()
connected_students = set()
students_names = {}

student_windows = {}
student_choices = {}

selected_student = None

window_choices = {}
selected_window = None
command_queues = {}
command_lock = threading.Lock()
command_results = queue.Queue()

def create_proof(access_code,message):
    key_bytes = access_code.encode("utf-8")
    message_bytes = message.encode("utf-8")

    result = hmac.new(
        key_bytes,
        message_bytes,
        hashlib.sha256
    )

    proof = result.hexdigest()

    return proof


def authenticate_student(connection, incoming, access_code):
    challenge = secrets.token_hex(32)

    connection.sendall((challenge + "\n").encode("ascii"))

    student_proof_bytes = incoming.readline(66)

    expected_proof = create_proof(access_code,"student:"+challenge)
    expected_bytes = (expected_proof + "\n").encode("ascii")

    if not hmac.compare_digest(student_proof_bytes,expected_bytes):
        return False

    teacher_proof = create_proof(access_code,"teacher:" + challenge)

    connection.sendall((teacher_proof + "\n").encode("ascii"))

    return True


def select_window(event=None):
    """Запомнить выбранное окно из постоянно видимого списка."""
    global selected_window
    selection = windows_tree.selection()
    selected_window = window_choices.get(selection[0]) if selection else None
    if selected_window:
        action_status.configure(text=f"Выбрано: {selected_window['title']}")
    close_button.configure(state="normal" if selected_window else "disabled")
        # ...пока выводим его данные в консоль для проверки.



def update_window_menu():
    """Обновить только изменившиеся строки, сохранив выбор и прокрутку."""
    global selected_window
    windows = student_windows.get(selected_student, [])
    new_choices = {}
    for window in windows:
        title = window.get("title")
        handle, pid = window.get("handle"), window.get("pid")
        if isinstance(title, str) and type(handle) is int and type(pid) is int:
            row_id = f"{handle}:{pid}"
            new_choices[row_id] = window

    old_selection = windows_tree.selection()
    for row_id in windows_tree.get_children():
        if row_id not in new_choices:
            windows_tree.delete(row_id)
    for row_id, window in new_choices.items():
        if windows_tree.exists(row_id):
            if windows_tree.item(row_id, "text") != window["title"]:
                windows_tree.item(row_id, text=window["title"])
        else:
            windows_tree.insert("", "end", iid=row_id, text=window["title"])

    window_choices.clear()
    window_choices.update(new_choices)
    selected_window = window_choices.get(old_selection[0]) if old_selection else None
    close_button.configure(state="normal" if selected_window else "disabled")
    count = len(new_choices)
    if selected_student is None:
        windows_caption.configure(text="Выберите компьютер")
    elif selected_student not in student_windows:
        windows_caption.configure(text="Ожидание списка окон…")
    else:
        windows_caption.configure(text=f"Открытых окон: {count}. Выберите строку для закрытия.")
        # ...просим преподавателя сделать выбор.




def show_selected_windows():
    """Обновить список окон выбранного подключения."""
    update_window_menu()
        # Показываем преподавателю только заголовок.


def select_student(choice):
    """Переключить компьютер и сбросить выбор окна прежнего ученика."""
    global selected_student, selected_window
    address = student_choices.get(choice)
    if address != selected_student:
        selected_student = address
        selected_window = None
        windows_tree.selection_remove(*windows_tree.selection())
        action_status.configure(text="Выберите окно в списке")
    show_selected_windows()


def update_connected_list():
    """Обновить меню компьютеров, только когда варианты изменились."""
    global selected_student, selected_window
    old_student = selected_student
    choices = {}
    for address in sorted(connected_students):
        ip_address, port = address
        name = students_names.get(address, "Получение имени…")
        choices[f"{name} — {ip_address}:{port}"] = address
    student_choices.clear()
    student_choices.update(choices)
    values = list(choices) or ["Нет подключений"]
    if student_menu.cget("values") != values:
        student_menu.configure(values=values)
    student_menu.configure(state="normal" if choices else "disabled")
    if not choices:
        selected_student = None
    elif selected_student not in connected_students:
        selected_student = next(iter(choices.values()))
    if selected_student != old_student:
        selected_window = None
        windows_tree.selection_remove(*windows_tree.selection())
    label = next((label for label, address in choices.items() if address == selected_student), "Нет подключений")
    if student_menu.get() != label:
        student_menu.set(label)
    connection_count.configure(text=f"Подключено: {len(choices)}")
    show_selected_windows()


def check_student_events():
    """Обработать одно обновление окон из очереди и запланировать следующую проверку."""
    try:
        address, computer_name, window_titles = student_events.get_nowait()
    except queue.Empty:
        pass
    else:
        if address in connected_students:
            students_names[address] = computer_name
            student_windows[address] = window_titles
            update_connected_list()
    app.after(100, check_student_events)


def handle_student(connection, address,access_code):
    """Обрабатывать сообщения одного клиента до отключения или ошибки.

    connection — сокет клиента; address — кортеж его IP-адреса и порта.
    Данные интерфейса передаются в основной поток через очереди.
    """
    print("Подключился компьютер:", address)
    authenticated = False
    commands = queue.Queue(maxsize=1)

    try:
        connection.settimeout(10)
        with connection.makefile("rb") as incoming:
            if not authenticate_student(connection, incoming, access_code):
                print("Неверный код доступа:",address)
                return
            authenticated = True
            with command_lock:
                command_queues[address] = commands
            presence_events.put(("connected",address))
            while True:
                message_bytes = incoming.readline(65537)

                if not message_bytes:
                    print("Ученик отключился:",address)
                    break

                if len(message_bytes) > 65536:
                    print("ообщение слишком большое:",address)
                    break

                if not message_bytes.endswith(b"\n"):
                    print("Сообщение получено не полностью:",address)
                    break

                message = message_bytes.decode("utf-8")
                data = json.loads(message)

                if not isinstance(data,dict):
                    print("Получен неверный формат данных:",address)
                    break

                computer_name = data.get("computer_name")
                window_titles = data.get("windows")

                if not isinstance(computer_name,str):
                    print("Не получено имя компьютера:",address)
                    break

                if not isinstance(window_titles,list):
                    print("не получен списко окон:",address)
                    break

                if not all(isinstance(window, dict) for window in window_titles):
                    # Проверяем, что каждый элемент списка является словарём.

                    print("Список окон содержит неверные данные:", address)
                    # Сообщаем об ошибке в консоль.

                    break
                    # Прекращаем обработку этого подключения.

                student_events.put((address, computer_name, window_titles))
                result = data.get("close_result")
                if isinstance(result, str) and len(result) <= 500:
                    command_results.put((address, result))
                try:
                    command = commands.get_nowait()
                except queue.Empty:
                    command = {"action": "wait"}
                reply = json.dumps(command, ensure_ascii=False) + "\n"
                connection.sendall(reply.encode("utf-8"))

    except (OSError,UnicodeDecodeError,json.JSONDecodeError) as error:
        print("Ошибка при обмене с учеником:",address,error)
    finally:
        connection.close()
        if authenticated:
            with command_lock:
                command_queues.pop(address, None)
            presence_events.put(("disconnected",address))
        print("Соединение закрыто:",address)


def wait_for_students(access_code):
    """Принимать локальные TCP-подключения и запускать поток для каждого клиента."""
    try:
        with sc.socket(sc.AF_INET,sc.SOCK_STREAM) as server_socket:
            server_socket.bind(("127.0.0.1", SERVER_PORT))
            server_socket.listen()
            server_events.put(("started", f"Сервер запущен · порт {SERVER_PORT}"))
            print("Сервер ожидает подключения...")

            while True:
                connection, address = server_socket.accept()
                student_thread = threading.Thread(
                    target=handle_student,
                    args=(connection,address,access_code),
                    daemon=True
                )

                student_thread.start()

    except  OSError as error:
        print("Ошибка сервера:",error)
        server_events.put(("error", f"Не удалось запустить сервер: {error}"))


def start_server():
    access_code = code_entry.get()

    if access_code == "":
        status_label.configure(text="Введите код доступа")
    elif len(access_code) < 12:
        status_label.configure(text="Код должен содержать не менее 12 символов")
    else:
        server_thread = threading.Thread(
            target = wait_for_students,
            args=(access_code,),
            daemon=True
        )
        status_label.configure(text="Сервер запускается - проверьте консоль")
        start_button.configure(state="disabled")
        server_thread.start()


def check_server_events():
    """Показать результат запуска сервера и разрешить повтор при ошибке."""
    try:
        event_type, message = server_events.get_nowait()
    except queue.Empty:
        pass
    else:
        status_label.configure(text=message)
        if event_type == "error":
            start_button.configure(state="normal")
    app.after(100, check_server_events)


def check_presence_events():
    try:
        event_type, address = presence_events.get_nowait()
    except queue.Empty:
        pass
    else:
        if event_type == "connected":
            connected_students.add(address)
        elif event_type == "disconnected":
            connected_students.discard(address)
            students_names.pop(address, None)
            student_windows.pop(address, None)
        update_connected_list()
    app.after(100, check_presence_events)


def request_selected_close():
    """Поставить запрос для выбранного ученика после подтверждения."""
    if selected_student not in connected_students or selected_window is None:
        messagebox.showinfo("Закрытие окна", "Сначала выберите компьютер и окно.")
        return
    address = selected_student
    window = selected_window.copy()
    if window not in student_windows.get(address, []):
        messagebox.showwarning("Закрытие окна", "Список изменился. Выберите окно ещё раз.")
        return
    title = window.get("title", "Окно")
    if not messagebox.askyesno("Закрыть окно", f"Отправить запрос на закрытие окна «{title}»?"):
        return
    if address not in connected_students or window not in student_windows.get(address, []):
        messagebox.showwarning("Закрытие окна", "Компьютер или окно больше недоступны.")
        return
    command = {"action": "close", "handle": window.get("handle"),
               "pid": window.get("pid"), "title": title}
    with command_lock:
        commands = command_queues.get(address)
        if commands is None:
            messagebox.showwarning("Закрытие окна", "Компьютер уже отключился.")
            return
        try:
            commands.put_nowait(command)
        except queue.Full:
            messagebox.showinfo("Закрытие окна", "Предыдущий запрос ещё ожидает отправки.")
            return
    action_status.configure(text="Запрос ожидает отправки выбранному компьютеру")


def check_command_results():
    """Показать результат выполнения запроса из очереди интерфейса."""
    try:
        address, result = command_results.get_nowait()
    except queue.Empty:
        pass
    else:
        action_status.configure(text=f"{address[0]}:{address[1]} — {result}")
    app.after(100, check_command_results)


app = ctk.CTk()
app.title("Класс — панель преподавателя")
app.geometry("920x740")
app.minsize(650, 620)
app.configure(fg_color="#101720")

style = ttk.Style(app)
style.theme_use("clam")
style.configure("Classroom.Treeview", background="#1c2937", fieldbackground="#1c2937",
                foreground="#eff5fa", borderwidth=0, rowheight=36, font=("Segoe UI", 11))
style.map("Classroom.Treeview", background=[("selected", "#2c6f9e")], foreground=[("selected", "white")])

content = ctk.CTkFrame(app, fg_color="transparent")
content.pack(fill="both", expand=True, padx=28, pady=24)
ctk.CTkLabel(content, text="Панель преподавателя", font=ctk.CTkFont(size=25, weight="bold"),
             anchor="w").pack(fill="x")
ctk.CTkLabel(content, text="Подключения и открытые окна класса", text_color="#a8b9c8", anchor="w").pack(fill="x", pady=(2, 16))

server_card = ctk.CTkFrame(content, fg_color="#192532", corner_radius=12)
server_card.pack(fill="x", pady=(0, 12))
ctk.CTkLabel(server_card, text="1  •  Сервер", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").pack(fill="x", padx=18, pady=(12, 3))
server_row = ctk.CTkFrame(server_card, fg_color="transparent")
server_row.pack(fill="x", padx=18, pady=(4, 4))
code_entry = ctk.CTkEntry(server_row, placeholder_text="Код доступа (не менее 12 символов)", show="*", height=36)
code_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
start_button = ctk.CTkButton(server_row, text="Запустить сервер", command=start_server, height=36)
start_button.pack(side="left")
status_label = ctk.CTkLabel(server_card, text="Сервер не запущен", text_color="#a8b9c8", anchor="w")
status_label.pack(fill="x", padx=18, pady=(0, 10))

student_card = ctk.CTkFrame(content, fg_color="#192532", corner_radius=12)
student_card.pack(fill="x", pady=(0, 12))
student_header = ctk.CTkFrame(student_card, fg_color="transparent")
student_header.pack(fill="x", padx=18, pady=(10, 4))
ctk.CTkLabel(student_header, text="2  •  Компьютер", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
connection_count = ctk.CTkLabel(student_header, text="Подключено: 0", text_color="#a8b9c8")
connection_count.pack(side="right")
student_menu = ctk.CTkOptionMenu(student_card, values=["Нет подключений"], command=select_student,
                                 state="disabled", height=36)
student_menu.pack(fill="x", padx=18, pady=(3, 14))
student_menu.set("Нет подключений")

window_card = ctk.CTkFrame(content, fg_color="#192532", corner_radius=12)
window_card.pack(fill="both", expand=True)
ctk.CTkLabel(window_card, text="3  •  Открытые окна", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").pack(fill="x", padx=18, pady=(12, 0))
windows_caption = ctk.CTkLabel(window_card, text="Выберите компьютер", text_color="#a8b9c8", anchor="w")
windows_caption.pack(fill="x", padx=18, pady=(0, 8))
list_frame = ctk.CTkFrame(window_card, fg_color="transparent")
windows_tree = ttk.Treeview(list_frame, show="tree", selectmode="browse", style="Classroom.Treeview")
scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=windows_tree.yview)
windows_tree.configure(yscrollcommand=scrollbar.set)
scrollbar.pack(side="right", fill="y")
windows_tree.pack(side="left", fill="both", expand=True)
windows_tree.bind("<<TreeviewSelect>>", select_window)
action_row = ctk.CTkFrame(window_card, fg_color="transparent")
close_button = ctk.CTkButton(action_row, text="Закрыть выбранное окно", command=request_selected_close,
                             state="disabled", fg_color="#ac3e47", hover_color="#8e3038", height=36)
close_button.pack(side="left")
action_status = ctk.CTkLabel(window_card, text="Выберите окно в списке", text_color="#a8b9c8", anchor="w", wraplength=600)
action_status.pack(side="bottom", fill="x", padx=18, pady=(0, 12))
action_row.pack(side="bottom", fill="x", padx=18, pady=(12, 4))
list_frame.pack(fill="both", expand=True, padx=18)

app.after(100, check_student_events)
app.after(100, check_presence_events)
app.after(100, check_command_results)
app.after(100, check_server_events)
app.mainloop()
