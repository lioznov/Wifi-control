import queue
import socket as sc
import threading
import json
from ipaddress import ip_address
import hashlib
import hmac
import secrets

import customtkinter as ctk

ctk.set_appearance_mode("dark")

student_events = queue.Queue()
presence_events = queue.Queue()
connected_students = set()
students_names = {}

student_windows = {}
student_choices = {}

selected_student = None


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


def show_selected_windows():
    """Показать последний список окон выбранного подключения."""
    history_box.delete("1.0","end")

    if selected_student is None:
        history_box.insert("end","Выберите подключенный компьютер\n")
        return

    computer_name = students_names.get(selected_student,"получение имени...")
    ip_address,port = selected_student
    history_box.insert("end",f"{computer_name} - {ip_address}:{port}\n")

    windows = student_windows.get(selected_student)

    if windows is None:
        history_box.insert("end","Ожидание списка окон...\n")
        return

    if not windows:
        history_box.insert("end","Открытыъ окон не найдено\n")
        return

    for title in windows:
        history_box.insert("end",f" • {title}\n")


def select_student(choice):
    """Выбрать подключение по надписи из меню и показать его окна."""
    global selected_student
    selected_student = student_choices.get(choice)
    show_selected_windows()


def update_connected_list():
    """Обновить меню подключений, сохранив выбор, если он ещё доступен."""
    global selected_student
    student_choices.clear()
    for address in sorted(connected_students):
        ip_address, port = address
        computer_name = students_names.get(address, "Получение имени...")
        label = f"{computer_name} — {ip_address}:{port}"
        student_choices[label] = address

    if not student_choices:
        selected_student = None
        student_menu.configure(values=["Нет подключений"], state="disabled")
        student_menu.set("Нет подключений")
        show_selected_windows()
        return

    student_menu.configure(values=list(student_choices), state="normal")

    if selected_student not in connected_students:
        selected_student = next(iter(student_choices.values()))

    for label, address in student_choices.items():
        if address == selected_student:
            student_menu.set(label)
            break

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
    presence_events.put(("connected",address))

    try:
        connection.settimeout(10)
        with connection.makefile("rb") as incoming:
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

                if not all(isinstance(title,str) for title in window_titles):
                    print("Список окон содержит неверные данные:",address)
                    break

                student_events.put((address, computer_name, window_titles))
                reply = "Список получен\n"
                connection.sendall(reply.encode("utf-8"))

    except (OSError,UnicodeDecodeError,json.JSONDecodeError) as error:
        print("Ошибка при обмене с учеником:",address,error)
    finally:
        connection.close()
        presence_events.put(("disconnected",address))
        print("Соединение закрыто:",address)


def wait_for_students(access_code):
    """Принимать локальные TCP-подключения и запускать поток для каждого клиента."""
    try:
        with sc.socket(sc.AF_INET,sc.SOCK_STREAM) as server_socket:
            server_socket.bind(("127.0.0.1",50505))
            server_socket.listen()
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
        server_thread.start()

        status_label.configure(text="Сервер запускается - проверьте консоль")
        start_button.configure(state="disabled")


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


app = ctk.CTk()


app.title("Панель преподователя")
app.geometry("700x700")


title_label = ctk.CTkLabel(
    master=app,
    text="Управление компьютерным классом"
)
title_label.pack(pady=20)


status_label = ctk.CTkLabel(
    master=app,
    text="Сервер не запущен"
)
status_label.pack(pady=10)

student_label = ctk.CTkLabel(
    master=app,
    text="Подключений еще не было"
)
student_label.pack(pady=10)


connected_label = ctk.CTkLabel(
    master=app,
    text="Активные подключения"
)
connected_label.pack(pady=(10,5))


student_menu = ctk.CTkOptionMenu(
    master=app,                      # Меню находится в окне преподавателя.
    values=["Нет подключений"],      # Начальный пункт до подключения учеников.
    command=select_student,          # Функция вызовется при выборе пункта.
    width=400,                       # Ширина меню.
    state="disabled"                 # Пока учеников нет, меню отключено.
)

student_menu.pack(pady=5)             # Размещаем меню в окне.
student_menu.set("Нет подключений")   # Показываем начальную надпись.


history_label = ctk.CTkLabel(
    master=app,
    text="История подключений"
)
history_label.pack(pady=(15,5))

history_box = ctk.CTkTextbox(
    master=app,
    width=400,
    height=150
)
history_box.pack(pady=5)


code_entry = ctk.CTkEntry(
    master=app,
    placeholder_text="Придумайте код доступа",
    show="*",
    width=250
)
code_entry.pack(pady=10)


start_button = ctk.CTkButton(
    master=app,
    text="Запустить сервер",
    command=start_server
)
start_button.pack(pady=10)

test_code = "мой-длинный-код-123"  # Учебный пример, не настоящий код класса.
test_message = "проверка"          # Одинаковый текст для обеих программ.

print(create_proof(test_code, test_message))
# Выводим результат в консоль PyCharm.

app.after(100,check_student_events)
app.after(100,check_presence_events)
app.mainloop()
