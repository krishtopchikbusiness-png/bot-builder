# db.py
# =========================================================
# Зачем этот файл:
# - здесь вся работа с Postgres (Railway)
# - отдельный файл, чтобы не смешивать базу с логикой бота
# =========================================================

import os
import time
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Нет DATABASE_URL в Railway Variables")

def now_ts() -> int:
    return int(time.time())

def conn():
    # sslmode=require нужен для Railway Postgres
    return psycopg.connect(DATABASE_URL, sslmode="require", row_factory=dict_row)

def init_db():
    # =====================================================
    # Таблица users:
    # - хранит состояние пользователя (на каком экране)
    # - бан
    # =====================================================
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                first_name TEXT DEFAULT '',
                username TEXT DEFAULT '',
                last_seen_ts BIGINT DEFAULT 0,
                banned INTEGER DEFAULT 0,
                last_screen TEXT DEFAULT 'start'
            );
            """)

            # =================================================
            # bot_msgs:
            # - храним msg_id сообщений бота, чтобы потом удалить
            # - это и делает эффект "исчезновения"
            # =================================================
            cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_msgs (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                msg_id BIGINT NOT NULL
            );
            """)

            # =================================================
            # my_bots:
            # - "Мои боты" в конструкторе
            # - пока просто список (название + ссылка/юзернейм)
            # =================================================
            cur.execute("""
            CREATE TABLE IF NOT EXISTS my_bots (
                id BIGSERIAL PRIMARY KEY,
                owner_id BIGINT NOT NULL,
                title TEXT NOT NULL,
                bot_link TEXT NOT NULL,
                created_ts BIGINT NOT NULL
            );
            """)

        c.commit()

def upsert_user(user_id: int, first_name: str, username: str):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
            INSERT INTO users(user_id, first_name, username, last_seen_ts)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (user_id) DO UPDATE SET
                first_name=EXCLUDED.first_name,
                username=EXCLUDED.username,
                last_seen_ts=EXCLUDED.last_seen_ts
            """, (user_id, first_name or "", username or "", now_ts()))
        c.commit()

def get_user(user_id: int):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
            return cur.fetchone()

def set_user_field(user_id: int, field: str, value):
    allowed = {"banned", "last_screen"}
    if field not in allowed:
        raise ValueError("Bad field")
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(f"UPDATE users SET {field}=%s WHERE user_id=%s", (value, user_id))
        c.commit()

# ---------- Сообщения бота (для удаления) ----------

def add_bot_msg(user_id: int, msg_id: int):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("INSERT INTO bot_msgs(user_id, msg_id) VALUES(%s,%s)", (user_id, msg_id))
        c.commit()

def list_bot_msgs(user_id: int) -> list[int]:
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("SELECT msg_id FROM bot_msgs WHERE user_id=%s ORDER BY id ASC", (user_id,))
            return [int(r["msg_id"]) for r in cur.fetchall()]

def clear_bot_msgs(user_id: int):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("DELETE FROM bot_msgs WHERE user_id=%s", (user_id,))
        c.commit()

# ---------- Мои боты ----------

def add_my_bot(owner_id: int, title: str, bot_link: str):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
            INSERT INTO my_bots(owner_id, title, bot_link, created_ts)
            VALUES(%s,%s,%s,%s)
            """, (owner_id, title, bot_link, now_ts()))
        c.commit()

def list_my_bots(owner_id: int):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute("""
            SELECT id, title, bot_link, created_ts
            FROM my_bots
            WHERE owner_id=%s
            ORDER BY id DESC
            LIMIT 50
            """, (owner_id,))
            return cur.fetchall()
