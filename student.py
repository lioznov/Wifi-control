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
SERVER_PORT = 47473


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
    # Собираем данные видимых окон Windows.

    windows = []
    # Создаём пустой список для словарей с данными окон.

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    # Получаем доступ к функциям Windows для работы с окнами.

    excluded_titles = {
        "компьютер ученика",
        "program manager",
        "интерфейс ввода windows",
        "windows input experience"
    }
    # Эти заголовки пока исключаем из списка по точному совпадению.

    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    # IsWindowVisible принимает идентификатор окна.

    user32.IsWindowVisible.restype = wintypes.BOOL
    # Функция возвращает значение «истина» или «ложь».

    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    # Функция длины заголовка принимает идентификатор окна.

    user32.GetWindowTextLengthW.restype = ctypes.c_int
    # Она возвращает целое число — длину заголовка.

    user32.GetWindowTextW.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int
    ]
    # GetWindowTextW принимает окно, буфер текста и размер буфера.

    user32.GetWindowTextW.restype = ctypes.c_int
    # Возвращает число скопированных символов.

    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD)
    ]
    # Функция принимает окно и адрес переменной для номера процесса.

    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    # Возвращает номер потока, создавшего окно, или 0 при ошибке.

    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM
    )
    # Описываем тип функции, которую Windows вызовет для каждого окна.

    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    # EnumWindows принимает обработчик окон и дополнительные данные.

    user32.EnumWindows.restype = wintypes.BOOL
    # EnumWindows возвращает значение успеха или ошибки.

    def process_window(hwnd, extra_data):
        # Эта вложенная функция обрабатывает одно окно.

        if not user32.IsWindowVisible(hwnd):
            # Если окно не считается видимым...

            return True
            # ...пропускаем его и продолжаем перебор.

        title_length = user32.GetWindowTextLengthW(hwnd)
        # Узнаём длину заголовка окна.

        if title_length <= 0:
            # Если заголовок пустой...

            return True
            # ...пропускаем окно.

        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        # Создаём буфер для заголовка и завершающего нулевого символа.

        user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)
        # Просим Windows записать заголовок в буфер.

        title = title_buffer.value
        # Получаем строку заголовка из буфера.

        if title.strip().casefold() in excluded_titles:
            # Если заголовок находится в наборе исключений...

            return True
            # ...пропускаем это окно.

        process_id = wintypes.DWORD()
        # Создаём переменную, в которую Windows запишет номер процесса.

        thread_id = user32.GetWindowThreadProcessId(
            hwnd,
            ctypes.byref(process_id)
        )
        # Получаем номер процесса окна.
        # byref передаёт адрес переменной process_id.

        if thread_id == 0:
            # Если Windows не смогла получить информацию об окне...

            return True
            # ...пропускаем окно.

        if process_id.value == os.getpid():
            # Если окно принадлежит самой программе ученика...

            return True
            # ...не добавляем его в список доступных окон.

        window_data = {
            "title": title,
            "handle": int(hwnd),
            "pid": process_id.value
        }
        # Создаём словарь с заголовком, идентификатором окна и процесса.

        windows.append(window_data)
        # Добавляем словарь в итоговый список.

        return True
        # Сообщаем Windows, что перебор нужно продолжить.

    callback = callback_type(process_window)
    # Подготавливаем обработчик в формате, который ожидает Windows.

    result = user32.EnumWindows(callback, 0)
    # Запускаем перебор окон; 0 — неиспользуемые дополнительные данные.

    if not result:
        # Если сам перебор окон завершился ошибкой...

        raise ctypes.WinError(ctypes.get_last_error())
        # ...создаём исключение с информацией об ошибке Windows.

    return windows
    # Возвращаем полный список словарей с данными окон.


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


def request_window_close(window_handle, expected_pid):
    # window_handle — идентификатор окна Windows.
    # expected_pid — идентификатор процесса, которому окно должно принадлежать.

    if type(window_handle) is not int or not 0 < window_handle < 2 ** (ctypes.sizeof(ctypes.c_void_p) * 8):
        # Отклоняем неверный идентификатор и ноль.
        # Ноль нельзя использовать как обычный идентификатор целевого окна.

        return "Неверный идентификатор окна"

    if window_handle == 0xFFFF:
        # В Windows 0xFFFF имеет специальное значение широковещательной отправки.
        # Нам нельзя отправлять запрос всем окнам.

        return "Недопустимый идентификатор окна"

    if type(expected_pid) is not int or not 0 < expected_pid <= 0xFFFFFFFF:
        # Проверяем, что идентификатор процесса — положительное целое число.

        return "Неверный идентификатор процесса"

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    # Получаем доступ к функциям Windows для работы с окнами.

    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD)
    ]
    # Описываем типы аргументов функции Windows:
    # идентификатор окна и указатель на переменную для номера процесса.

    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    # Указываем, какой тип результата возвращает функция Windows.

    user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM
    ]
    # Описываем типы аргументов функции отправки сообщения.

    user32.PostMessageW.restype = wintypes.BOOL
    # PostMessageW возвращает значение успеха или ошибки.

    process_id = wintypes.DWORD()
    # Создаём переменную Windows, куда будет записан номер процесса.

    thread_id = user32.GetWindowThreadProcessId(
        window_handle,
        ctypes.byref(process_id)
    )
    # Запрашиваем у Windows процесс, которому принадлежит окно.
    # byref(process_id) передаёт адрес переменной для результата.

    if thread_id == 0:
        # Windows не смогла получить данные об этом окне.

        return "Окно не найдено или уже закрыто"

    if process_id.value != expected_pid:
        # Окно теперь принадлежит не тому процессу, который мы ожидали.

        return "Окно изменилось: запрос отменён"

    if process_id.value == os.getpid():
        # Не позволяем программе ученика закрыть собственное окно.

        return "Нельзя закрыть программу ученика"

    wm_close = 0x0010
    # Числовой код сообщения Windows WM_CLOSE.

    sent = user32.PostMessageW(window_handle, wm_close, 0, 0)
    # Просим Windows поместить сообщение закрытия в очередь окна.
    # Последние два параметра для WM_CLOSE не используются, поэтому передаём 0.

    if not sent:
        # Если Windows не приняла запрос...

        error_code = ctypes.get_last_error()
        # ...получаем код последней ошибки Windows.

        return f"Не удалось отправить запрос. Код Windows: {error_code}"

    return "Запрос на закрытие отправлен"
    # Это подтверждает отправку запроса, а не фактическое закрытие окна.




def try_connection(ip_address,access_code):
    """Подключиться к преподавателю и отправлять списки окон до ошибки связи.

    ip_address — адрес сервера; результаты передаются в интерфейс через очередь.
    """
    try:
        with socket.create_connection((ip_address, SERVER_PORT), timeout=10) as connection:
            with connection.makefile("rb") as incoming:
                authenticate_teacher(connection, incoming, access_code)
                connection_results.put(("connected", "Код подтверждён. Соединение установлено"))
                close_result = None
                while True:
                    computer_name = socket.gethostname()
                    window_titles = show_open_windows()

                    data = {
                        "computer_name": computer_name,
                        "windows": window_titles
                    }
                    if close_result is not None:
                        data["close_result"] = close_result
                        close_result = None

                    json_text = json.dumps(data, ensure_ascii=False)
                    message = json_text + "\n"

                    connection.sendall(message.encode("utf-8"))

                    reply_bytes = incoming.readline(65537)

                    if len(reply_bytes) > 65536 or not reply_bytes.endswith(b"\n"):
                        raise ConnectionError("Ответ не получен полностью")

                    reply = json.loads(reply_bytes.decode("utf-8"))
                    if not isinstance(reply, dict):
                        raise ValueError("Неверный формат команды")
                    action = reply.get("action")
                    if action == "close":
                        target = {"handle": reply.get("handle"), "pid": reply.get("pid"),
                                  "title": reply.get("title")}
                        if target not in window_titles:
                            close_result = "Окно изменилось или отсутствует в последнем списке"
                        else:
                            close_result = request_window_close(target["handle"], target["pid"])
                        print("Результат запроса:", close_result)
                    elif action != "wait":
                        raise ValueError("Неизвестная команда преподавателя")

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
app.title("Класс — компьютер ученика")
app.geometry("560x440")
app.minsize(500, 420)
app.configure(fg_color="#101720")

content = ctk.CTkFrame(app, fg_color="transparent")
content.pack(fill="both", expand=True, padx=32, pady=28)
ctk.CTkLabel(content, text="Компьютер ученика", font=ctk.CTkFont(size=24, weight="bold"), anchor="w").pack(fill="x")
ctk.CTkLabel(content, text="Подключение к преподавателю", text_color="#a8b9c8", anchor="w").pack(fill="x", pady=(2, 18))

card = ctk.CTkFrame(content, fg_color="#192532", corner_radius=12)
card.pack(fill="x")
ctk.CTkLabel(card, text="Адрес компьютера преподавателя", anchor="w").pack(fill="x", padx=20, pady=(16, 3))
ip_entry = ctk.CTkEntry(card, placeholder_text="Например, 127.0.0.1", height=36)
ip_entry.pack(fill="x", padx=20)
ctk.CTkLabel(card, text="Общий код доступа", anchor="w").pack(fill="x", padx=20, pady=(12, 3))
code_entry = ctk.CTkEntry(card, placeholder_text="Код преподавателя", show="*", height=36)
code_entry.pack(fill="x", padx=20)
connect_button = ctk.CTkButton(card, text="Подключиться", command=connect_to_teacher, height=38)
connect_button.pack(fill="x", padx=20, pady=(18, 16))
status_label = ctk.CTkLabel(content, text="Нет подключения", anchor="w", text_color="#a8b9c8", wraplength=450)
status_label.pack(fill="x", pady=(16, 4))
ctk.CTkLabel(content, text="Преподаватель видит открытые окна и может запросить их закрытие.",
             text_color="#8599a9", anchor="w", wraplength=450, justify="left").pack(fill="x")

app.after(100, check_connection_result)
app.mainloop()
