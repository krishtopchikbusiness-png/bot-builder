"""
db.py
ЗАЧЕМ:
- Postgres хранит всё: пользователей платформы, их ботов, блоки, кнопки, end-users.
- Ничего не слетает после деплоя.

ВАЖНО:
- Здесь token клиентского бота хранится как TEXT.
  Это фундамент. Потом можно добавить шифрование (лучше сделать).
"""

from __future__ import annotations
import asyncpg
from typing import Optional, List, Dict, Any

_pool: Optional[asyncpg.Pool] = None

async def init_pool(dsn: str) -> None:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)

def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool не инициализирован")
    return _pool

async def init_db() -> None:
    """
    Создаём все таблицы.
    """
    q = """
    CREATE TABLE IF NOT EXISTS platform_users (
        id BIGINT PRIMARY KEY,          -- telegram id пользователя платформы (кто строит бота)
        created_at TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS client_bots (
        id BIGSERIAL PRIMARY KEY,
        owner_id BIGINT NOT NULL REFERENCES platform_users(id) ON DELETE CASCADE,
        bot_username TEXT,
        bot_token TEXT NOT NULL,
        published BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_client_bots_owner ON client_bots(owner_id);

    -- состояние пользователя платформы (на каком шаге он сейчас)
    CREATE TABLE IF NOT EXISTS platform_state (
        user_id BIGINT PRIMARY KEY REFERENCES platform_users(id) ON DELETE CASCADE,
        screen TEXT NOT NULL DEFAULT 'welcome',
        last_message_id BIGINT,
        prev_screen TEXT,
        -- "ожидание ввода": например token / block_name / block_text / button_text
        pending_type TEXT,
        pending_payload JSONB
    );

    -- блоки (визуальные блоки)
    CREATE TABLE IF NOT EXISTS blocks (
        id BIGSERIAL PRIMARY KEY,
        bot_id BIGINT NOT NULL REFERENCES client_bots(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        text TEXT NOT NULL DEFAULT '',
        delete_prev BOOLEAN NOT NULL DEFAULT TRUE, -- "удаляемый экран" (твоя фишка)
        is_start BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_blocks_bot ON blocks(bot_id);

    -- кнопки внутри блока
    CREATE TABLE IF NOT EXISTS block_buttons (
        id BIGSERIAL PRIMARY KEY,
        block_id BIGINT NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        action_type TEXT NOT NULL,   -- 'go_block' | 'open_url' | 'send_text'
        action_value TEXT NOT NULL   -- id блока или url или текст
    );
    CREATE INDEX IF NOT EXISTS idx_buttons_block ON block_buttons(block_id);

    -- end-users: люди, которые пишут клиентскому боту
    CREATE TABLE IF NOT EXISTS end_users (
        bot_id BIGINT NOT NULL REFERENCES client_bots(id) ON DELETE CASCADE,
        tg_user_id BIGINT NOT NULL,
        current_block_id BIGINT,
        last_message_id BIGINT,
        PRIMARY KEY (bot_id, tg_user_id)
    );
    """
    async with pool().acquire() as conn:
        await conn.execute(q)

# ----------------------------
# Platform users
# ----------------------------

async def upsert_platform_user(user_id: int) -> None:
    async with pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO platform_users(id) VALUES($1) ON CONFLICT (id) DO NOTHING",
            user_id
        )
        await conn.execute(
            """
            INSERT INTO platform_state(user_id)
            VALUES($1)
            ON CONFLICT (user_id) DO NOTHING
            """,
            user_id
        )

async def get_platform_state(user_id: int) -> Dict[str, Any]:
    async with pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM platform_state WHERE user_id=$1", user_id)
        return dict(row) if row else {}

async def set_platform_state(
    user_id: int,
    *,
    screen: Optional[str] = None,
    last_message_id: Optional[int] = None,
    prev_screen: Optional[str] = None,
    pending_type: Optional[str] = None,
    pending_payload: Optional[dict] = None,
) -> None:
    async with pool().acquire() as conn:
        state = await conn.fetchrow("SELECT * FROM platform_state WHERE user_id=$1", user_id)
        if not state:
            await conn.execute("INSERT INTO platform_state(user_id) VALUES($1)", user_id)

        # обновляем только то, что передали
        fields = []
        vals = []
        idx = 1

        def add(field: str, value):
            nonlocal idx
            fields.append(f"{field}=${idx}")
            vals.append(value)
            idx += 1

        if screen is not None:
            add("screen", screen)
        if last_message_id is not None:
            add("last_message_id", last_message_id)
        if prev_screen is not None:
            add("prev_screen", prev_screen)
        if pending_type is not None:
            add("pending_type", pending_type)
        if pending_payload is not None:
            add("pending_payload", pending_payload)

        if not fields:
            return

        vals.append(user_id)
        await conn.execute(
            f"UPDATE platform_state SET {', '.join(fields)} WHERE user_id=${idx}",
            *vals
        )

# ----------------------------
# Client bots
# ----------------------------

async def create_client_bot(owner_id: int, token: str, username: str) -> int:
    async with pool().acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO client_bots(owner_id, bot_token, bot_username) VALUES($1,$2,$3) RETURNING id",
            owner_id, token, username
        )
        bot_id = int(row["id"])

        # создаём стартовый блок по умолчанию
        await conn.execute(
            "INSERT INTO blocks(bot_id, title, text, delete_prev, is_start) VALUES($1,$2,$3,$4,$5)",
            bot_id, "START", "Привет! Это стартовый блок. Настрой меня 🙂", True, True
        )
        return bot_id

async def list_client_bots(owner_id: int) -> List[Dict[str, Any]]:
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, bot_username, published, created_at FROM client_bots WHERE owner_id=$1 ORDER BY id DESC",
            owner_id
        )
        return [dict(r) for r in rows]

async def get_client_bot(bot_id: int) -> Optional[Dict[str, Any]]:
    async with pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM client_bots WHERE id=$1", bot_id)
        return dict(row) if row else None

async def set_client_bot_published(bot_id: int, published: bool) -> None:
    async with pool().acquire() as conn:
        await conn.execute("UPDATE client_bots SET published=$2 WHERE id=$1", bot_id, published)

# ----------------------------
# Blocks & buttons
# ----------------------------

async def list_blocks(bot_id: int) -> List[Dict[str, Any]]:
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, delete_prev, is_start FROM blocks WHERE bot_id=$1 ORDER BY is_start DESC, id ASC",
            bot_id
        )
        return [dict(r) for r in rows]

async def get_block(block_id: int) -> Optional[Dict[str, Any]]:
    async with pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM blocks WHERE id=$1", block_id)
        return dict(row) if row else None

async def get_start_block(bot_id: int) -> Optional[Dict[str, Any]]:
    async with pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM blocks WHERE bot_id=$1 AND is_start=TRUE LIMIT 1",
            bot_id
        )
        return dict(row) if row else None

async def create_block(bot_id: int, title: str) -> int:
    async with pool().acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO blocks(bot_id, title, text) VALUES($1,$2,$3) RETURNING id",
            bot_id, title, ""
        )
        return int(row["id"])

async def update_block_text(block_id: int, text: str) -> None:
    async with pool().acquire() as conn:
        await conn.execute("UPDATE blocks SET text=$2 WHERE id=$1", block_id, text)

async def toggle_block_delete_prev(block_id: int) -> None:
    async with pool().acquire() as conn:
        await conn.execute("UPDATE blocks SET delete_prev = NOT delete_prev WHERE id=$1", block_id)

async def list_buttons(block_id: int) -> List[Dict[str, Any]]:
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, action_type, action_value FROM block_buttons WHERE block_id=$1 ORDER BY id ASC",
            block_id
        )
        return [dict(r) for r in rows]

async def create_button(block_id: int, title: str, action_type: str, action_value: str) -> int:
    async with pool().acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO block_buttons(block_id, title, action_type, action_value) VALUES($1,$2,$3,$4) RETURNING id",
            block_id, title, action_type, action_value
        )
        return int(row["id"])

# ----------------------------
# End-users state (для клиентских ботов)
# ----------------------------

async def get_end_user(bot_id: int, tg_user_id: int) -> Optional[Dict[str, Any]]:
    async with pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM end_users WHERE bot_id=$1 AND tg_user_id=$2",
            bot_id, tg_user_id
        )
        return dict(row) if row else None

async def upsert_end_user(bot_id: int, tg_user_id: int, current_block_id: Optional[int], last_message_id: Optional[int]) -> None:
    async with pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO end_users(bot_id, tg_user_id, current_block_id, last_message_id)
            VALUES($1,$2,$3,$4)
            ON CONFLICT (bot_id, tg_user_id)
            DO UPDATE SET current_block_id=EXCLUDED.current_block_id, last_message_id=EXCLUDED.last_message_id
            """,
            bot_id, tg_user_id, current_block_id, last_message_id
        )
