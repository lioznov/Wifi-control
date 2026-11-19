import queue
import socket
import threading
import ctypes
import json
from ctypes import wintypes
import time
import hashlib
import hmac
import os

import customtkinter as ctk

ctk.set_appearance_mode("dark")


connection_results = queue.Queue()


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


def authenticate_teacher(connection, incoming, access_code):
    challenge_bytes = incoming.readline(66)
    if len(challenge_bytes) != 65 or not challenge_bytes.endswith(b"\n"):
        raise ValueError("Получена неверная строка проверки")
    challenge = challenge_bytes[:-1].decode("ascii")
    student_proof = create_proof(access_code, "student:" + challenge)
    connection.sendall((student_proof + "\n").encode("ascii"))
    teacher_proof_bytes = incoming.readline(66)
    expected_proof = create_proof(access_code, "teacher:" + challenge)
    expected_bytes = (expected_proof + "\n").encode("ascii")

    if not hmac.compare_digest(teacher_proof_bytes, expected_bytes):
        raise ValueError("Не удалось подтвердить код доступа")


def show_open_windows():
    """Вернуть заголовки видимых окон Windows после простой фильтрации."""
    window_titles = []
    user32 = ctypes.windll.user32

    excluded_titles = {
        "компьютер ученика",
        "program manager",
        "интерфейс ввода windows",
        "windows input experience"
    }

    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM
    )

    def process_window(hwnd, extra_data):
        """Добавить подходящий заголовок окна; вернуть True для продолжения перебора."""
        if user32.IsWindowVisible(hwnd):
            title_length = user32.GetWindowTextLengthW(hwnd)

            if title_length > 0:
                title_buffer = ctypes.create_unicode_buffer(title_length + 1)

                user32.GetWindowTextW(
                    hwnd,
                    title_buffer,
                    title_length + 1
                )

                title = title_buffer.value
                normalized_title = title.strip().casefold()
                if normalized_title not in excluded_titles:
                    window_titles.append(title)

        return True

    callback = callback_type(process_window)
    user32.EnumWindows(callback, 0)

    return window_titles


def print_open_windows():
    """Вывести в консоль пример JSON с именем компьютера и окнами."""
    titles = show_open_windows()

    data = {
        "computer_user": socket.gethostname(),
        "windows":titles
    }

    json_text = json.dumps(data, ensure_ascii=False)

    print("Данные в формате JSON: ")
    print(json_text)


def try_connection(ip_address,access_code):
    """Подключиться к преподавателю и отправлять списки окон до ошибки связи.

    ip_address — адрес сервера; результаты передаются в интерфейс через очередь.
    """
    try:
        with socket.create_connection((ip_address, 50505), timeout=10) as connection:
            with connection.makefile("rb") as incoming:
                authenticate_teacher(connection, incoming, access_code)
                connection_results.put(("connected", "Код подтверждён. Соединение установлено"))
                while True:
                    computer_name = socket.gethostname()
                    window_titles = show_open_windows()

                    data = {
                        "computer_name": computer_name,
                        "windows": window_titles
                    }

                    json_text = json.dumps(data, ensure_ascii=False)
                    message = json_text + "\n"

                    connection.sendall(message.encode("utf-8"))

                    reply_bytes = incoming.readline(1024)

                    if not reply_bytes.endswith(b"\n"):
                        raise ConnectionError("Ответ не получен полностью")

                    reply = reply_bytes.decode("utf-8").rstrip("\n")
                    print("Ответ преподавателя:", reply)

                    time.sleep(3)

    except OSError as error:
        connection_results.put(("disconnected", f"Соединение завершено: {error}"))

    except UnicodeDecodeError:
        connection_results.put(("disconnected", "Не удалось прочитать ответ"))

    except ValueError as error:
        connection_results.put(("disconnected", str(error)))

def check_connection_result():
    """Показать событие соединения из очереди и запланировать следующую проверку."""
    try:
        event_type, message = connection_results.get_nowait()
    except queue.Empty:
        pass
    else:
        status_label.configure(text=message)

        if event_type == "disconnected":
            connect_button.configure(state="normal")

    app.after(100, check_connection_result)


def connect_to_teacher():
    """Проверить введённые данные и запустить подключение в фоновом потоке."""
    ip_address = ip_entry.get().strip()
    access_code = code_entry.get()

    if ip_address == "":
        status_label.configure(text="Введите IP-адрес преподавателя")
    elif access_code == "":
        status_label.configure(text="Введите код доступа")
    elif len(access_code) < 12:
        status_label.configure(text="Код должен содержать не менее 12 символов")
    else:
        status_label.configure(text="Подключение...")
        connect_button.configure(state="disabled")

        connection_thread= threading.Thread(
            target=try_connection,
            args=(ip_address,access_code),
            daemon = True
        )

        connection_thread.start()


app = ctk.CTk()
app.title("Компьютер ученика")
app.geometry("500x350")


title_label = ctk.CTkLabel(
    master=app,
    text="Подключение к преподавателю"
)
title_label.pack(pady=20)


ip_entry = ctk.CTkEntry(
    master=app,
    placeholder_text="IP-адрес преподавателя",
    width=250
)
ip_entry.pack(pady=10)


code_entry = ctk.CTkEntry(
    master=app,
    placeholder_text="Введите код доступа",
    show="*",
    width=250
)
code_entry.pack(pady=10)


connect_button = ctk.CTkButton(
    master=app,
    text="Подключиться",
    command=connect_to_teacher
)
connect_button.pack(pady=10)


status_label = ctk.CTkLabel(
    master=app,
    text="Нет подключения"
)
status_label.pack(pady=20)


app.after(200, print_open_windows)
app.after(100, check_connection_result)

app.mainloop()
