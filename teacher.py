import queue
import socket as sc
import threading
import json

import customtkinter as ctk


ctk.set_appearance_mode("dark")

student_events = queue.Queue()


def check_student_events():
    try:
        address, computer_name, window_titles = student_events.get_nowait()
    except queue.Empty:
        pass
    else:
        ip_address, port = address

        student_label.configure(
            text=f"Последнее подключение: {computer_name} — {ip_address}"
        )

        record = f"{computer_name} — {ip_address}\n"
        history_box.insert("end", record)

        for title in window_titles:
            history_box.insert("end", f"  • {title}\n")

        history_box.insert("end", "\n")

    app.after(100, check_student_events)


def wait_for_student():
    server_socket = sc.socket(sc.AF_INET, sc.SOCK_STREAM)
    server_socket.bind(("127.0.0.1", 50505))
    server_socket.listen()

    print("Сервер ожидает подключения...")

    while True:
        connection, address = server_socket.accept()
        print("Подключился компьютер:", address)

        try:
            connection.settimeout(10)

            with connection.makefile("rb") as incoming:
                while True:
                    message_bytes = incoming.readline(65537)

                    if not message_bytes:
                        print("Ученик отключился:", address)
                        break

                    if len(message_bytes) > 65536 or not message_bytes.endswith(b"\n"):
                        print("Сообщение слишком большое или получено не полностью")
                        break

                    message = message_bytes.decode("utf-8")
                    data = json.loads(message)

                    computer_name = data["computer_name"]
                    window_titles = data["windows"]

                    student_events.put((address, computer_name, window_titles))

                    reply = "Список получен\n"
                    connection.sendall(reply.encode("utf-8"))

        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
            print("Ошибка при обмене с учеником:", error)

        finally:
            connection.close()

        print("Сервер снова ожидает подключения...")

def start_server():
    access_code = code_entry.get()

    if access_code == "":
        status_label.configure(text="Введите код доступа")
    elif len(access_code) < 12:
        status_label.configure(text="Код должен содержать не менее 12 символов")
    else:
        server_thread = threading.Thread(
            target = wait_for_student,
            daemon=True
        )
        server_thread.start()

        status_label.configure(text="Сервер запускается - проверьте консоль")
        start_button.configure(state="disabled")


app = ctk.CTk()


app.title("Панель преподователя")
app.geometry("500x500")


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

app.after(100, check_student_events)

app.mainloop()