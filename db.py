# db.py
# =========================================================
# ЗАЧЕМ ЭТО:
# - тут вся работа с Postgres: таблицы, чтение/запись
# - чтобы после перезапуска Railway ничего "не слетало"
# - чтобы "эффект исчезновения" работал (храним msg_id бота)
# - чтобы работали "Мои боты" (храним список ботов юзера)
# =========================================================

import os
import time
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional, List, Dict, Any

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Нет DATABASE_URL в Variables (Railway)")

def db():
    # ЗАЧЕМ: одно место где создаём подключение к Postgres
    # sslmode=require — стандартно для Railway Postgres
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def now_ts() -> int:
    return int(time.time())

def init_db():
    """
    ЗАЧЕМ:
    - создаём таблицы один раз при старте
    - если таблицы уже есть — ничего не ломаем
    """
    conn = db()
    cur = conn.cursor()

    # users: минимальный профиль пользователя
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        first_name TEXT DEFAULT '',
        username TEXT DEFAULT '',
        created_ts BIGINT DEFAULT 0,
        last_seen_ts BIGINT DEFAULT 0
    );
    """)

    # bot_msgs: msg_id всех сообщений, которые отправлял бот этому пользователю
    # чтобы потом удалить и сделать "экран исчез"
    cur.execute("""
    CREATE TABLE IF NOT EXISTS bot_msgs (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        chat_id BIGINT NOT NULL,
        msg_id BIGINT NOT NULL,
        created_ts BIGINT DEFAULT 0
    );
    """)

    # user_bots: "Мои боты" — список ботов пользователя (пока минимально)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_bots (
        id BIGSERIAL PRIMARY KEY,
        owner_id BIGINT NOT NULL,
        title TEXT NOT NULL,
        bot_username TEXT NOT NULL,
        created_ts BIGINT DEFAULT 0
    );
    """)

    conn.commit()
    cur.close()
    conn.close()

def upsert_user(user_id: int, first_name: str = "", username: str = ""):
    """
    ЗАЧЕМ:
    - фиксируем кто зашёл/написал
    - last_seen для будущей аналитики
    """
    conn = db()
    cur = conn.cursor()
    ts = now_ts()
    cur.execute("""
        INSERT INTO users(user_id, first_name, username, created_ts, last_seen_ts)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (user_id) DO UPDATE SET
            first_name = EXCLUDED.first_name,
            username = EXCLUDED.username,
            last_seen_ts = EXCLUDED.last_seen_ts
    """, (user_id, first_name or "", username or "", ts, ts))
    conn.commit()
    cur.close()
    conn.close()

def add_bot_msg(user_id: int, chat_id: int, msg_id: int):
    """
    ЗАЧЕМ:
    - запоминаем каждое сообщение бота
    - чтобы потом удалить и сделать "исчезновение"
    """
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO bot_msgs(user_id, chat_id, msg_id, created_ts) VALUES(%s,%s,%s,%s)",
        (user_id, chat_id, msg_id, now_ts())
    )
    conn.commit()
    cur.close()
    conn.close()

def get_bot_msgs(user_id: int, chat_id: int) -> List[int]:
    """
    ЗАЧЕМ:
    - список msg_id, которые бот отправлял юзеру
    """
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "SELECT msg_id FROM bot_msgs WHERE user_id=%s AND chat_id=%s ORDER BY id ASC",
        (user_id, chat_id)
    )
    ids = [int(r[0]) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return ids

def clear_bot_msgs(user_id: int, chat_id: int):
    """
    ЗАЧЕМ:
    - после удаления сообщений чистим список, чтобы не копился мусор
    """
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM bot_msgs WHERE user_id=%s AND chat_id=%s", (user_id, chat_id))
    conn.commit()
    cur.close()
    conn.close()

def list_user_bots(owner_id: int) -> List[Dict[str, Any]]:
    """
    ЗАЧЕМ:
    - экран "Мои боты"
    """
    conn = db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT id, title, bot_username, created_ts FROM user_bots WHERE owner_id=%s ORDER BY id DESC",
        (owner_id,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def add_user_bot(owner_id: int, title: str, bot_username: str) -> int:
    """
    ЗАЧЕМ:
    - пока простая "добавить бота" (потом заменим на настоящий конструктор)
    """
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO user_bots(owner_id, title, bot_username, created_ts) VALUES(%s,%s,%s,%s) RETURNING id",
        (owner_id, title.strip(), bot_username.strip().lstrip("@"), now_ts())
    )
    bot_id = int(cur.fetchone()[0])
    conn.commit()
    cur.close()
    conn.close()
    return bot_id

def get_user_bot(owner_id: int, bot_id: int) -> Optional[Dict[str, Any]]:
    conn = db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT id, title, bot_username, created_ts FROM user_bots WHERE owner_id=%s AND id=%s",
        (owner_id, bot_id)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

