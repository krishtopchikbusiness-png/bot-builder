"""
===========================================================
ФАЙЛ: db.py
===========================================================

ЗАЧЕМ ЭТОТ ФАЙЛ?

Этот файл отвечает ТОЛЬКО за работу с базой данных.
Тут нет логики бота.
Тут нет кнопок.
Тут нет экранов.

Здесь только:
- подключение к Postgres
- создание таблиц
- сохранение данных
- получение данных

Мы разделяем файлы специально,
чтобы потом можно было легко менять БД,
не трогая клиентскую часть.
===========================================================
"""

import os
import time
import psycopg2
from psycopg2.extras import RealDictCursor


# =========================================================
# ПОДКЛЮЧЕНИЕ К БАЗЕ ДАННЫХ
# =========================================================

"""
ЗАЧЕМ ЭТО?

Railway автоматически создаёт переменную DATABASE_URL,
когда ты подключаешь Postgres сервис.

Мы её забираем отсюда.
"""

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "❌ Нет DATABASE_URL. Проверь что Postgres подключен в Railway."
    )


def get_connection():
    """
    ЧТО ДЕЛАЕТ ЭТА ФУНКЦИЯ?

    Каждый раз когда нам нужно что-то записать или прочитать из базы,
    мы вызываем эту функцию.

    Она создаёт новое подключение к Postgres.

    ПОЧЕМУ ТАК?
    Railway может разрывать старые соединения.
    Поэтому безопаснее открывать новое на каждую операцию.
    """
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def current_timestamp():
    """
    ЗАЧЕМ НУЖНО?

    Возвращает текущее время в формате UNIX (число).
    Используется при создании пользователя и бота.
    """
    return int(time.time())


# =========================================================
# СОЗДАНИЕ ТАБЛИЦ
# =========================================================

def init_db():
    """
    ЧТО ДЕЛАЕТ?

    Создаёт таблицы, если их ещё нет.

    ЭТА ФУНКЦИЯ вызывается один раз при запуске бота.
    """

    conn = get_connection()
    cursor = conn.cursor()

    # -------------------------
    # Таблица пользователей
    # -------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            first_name TEXT DEFAULT '',
            username TEXT DEFAULT '',
            created_at BIGINT DEFAULT 0
        );
    """)

    # -------------------------
    # Таблица сообщений бота
    # Нужна чтобы удалять старые экраны
    # -------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_messages (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            message_id BIGINT NOT NULL
        );
    """)

    # -------------------------
    # Таблица ботов пользователя
    # -------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_bots (
            id BIGSERIAL PRIMARY KEY,
            owner_id BIGINT NOT NULL,
            bot_name TEXT NOT NULL,
            bot_username TEXT DEFAULT '',
            created_at BIGINT DEFAULT 0
        );
    """)

    conn.commit()
    cursor.close()
    conn.close()


# =========================================================
# РАБОТА С ПОЛЬЗОВАТЕЛЕМ
# =========================================================

def save_user(user_id: int, first_name: str = "", username: str = ""):
    """
    ЧТО ДЕЛАЕТ?

    Сохраняет пользователя в базу.
    Если пользователь уже есть — обновляет имя и username.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO users (user_id, first_name, username, created_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE
        SET first_name = EXCLUDED.first_name,
            username = EXCLUDED.username;
    """, (user_id, first_name or "", username or "", current_timestamp()))

    conn.commit()
    cursor.close()
    conn.close()


def get_user(user_id: int):
    """
    Возвращает данные пользователя.
    Используется в профиле.
    """

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("SELECT * FROM users WHERE user_id=%s;", (user_id,))
    result = cursor.fetchone()

    cursor.close()
    conn.close()

    return result


# =========================================================
# РАБОТА С СООБЩЕНИЯМИ (ДЛЯ ЭФФЕКТА ИСЧЕЗНОВЕНИЯ)
# =========================================================

def add_bot_message(user_id: int, message_id: int):
    """
    ЗАЧЕМ?

    Когда бот отправляет экран,
    мы сохраняем ID сообщения.

    Чтобы потом удалить его,
    когда пользователь нажмёт кнопку.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO bot_messages (user_id, message_id)
        VALUES (%s, %s);
    """, (user_id, message_id))

    conn.commit()
    cursor.close()
    conn.close()


def get_bot_messages(user_id: int):
    """
    Возвращает все сообщения бота,
    чтобы их удалить.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT message_id FROM bot_messages
        WHERE user_id=%s;
    """, (user_id,))

    result = cursor.fetchall()

    cursor.close()
    conn.close()

    return [row[0] for row in result]


def clear_bot_messages(user_id: int):
    """
    Удаляет записи сообщений из базы
    после того как мы их удалили в Telegram.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM bot_messages
        WHERE user_id=%s;
    """, (user_id,))

    conn.commit()
    cursor.close()
    conn.close()


# =========================================================
# РАБОТА С БОТАМИ ПОЛЬЗОВАТЕЛЯ
# =========================================================

def add_user_bot(owner_id: int, bot_name: str, bot_username: str = ""):
    """
    Добавляет нового бота пользователю.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO user_bots (owner_id, bot_name, bot_username, created_at)
        VALUES (%s, %s, %s, %s);
    """, (owner_id, bot_name, bot_username or "", current_timestamp()))

    conn.commit()
    cursor.close()
    conn.close()


def get_user_bots(owner_id: int):
    """
    Возвращает список ботов пользователя.
    Используется в разделе "Мои боты".
    """

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("""
        SELECT * FROM user_bots
        WHERE owner_id=%s
        ORDER BY id DESC;
    """, (owner_id,))

    result = cursor.fetchall()

    cursor.close()
    conn.close()

    return result
