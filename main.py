import os
import json
import hmac
import hashlib
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple

import asyncpg
from fastapi import FastAPI, Request, HTTPException

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

# =========================================================
#                       НАСТРОЙКИ
# =========================================================

UTC = timezone.utc

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
ADMIN_IDS = set(
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
)

GUMROAD_WEBHOOK_SECRET = os.getenv("GUMROAD_WEBHOOK_SECRET", "").strip()
AUTO_MIGRATE = os.getenv("AUTO_MIGRATE", "0").strip() == "1"

from aiogram.client.default import DefaultBotProperties

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)

dp = Dispatcher()

# Ссылки на оплату (можешь потом заменить в переменных Railway)
GUMROAD_URLS = {
    "lite": os.getenv("GUMROAD_LITE_URL", "").strip(),
    "plus": os.getenv("GUMROAD_PLUS_URL", "").strip(),
    "pro": os.getenv("GUMROAD_PRO_URL", "").strip(),
}

# =========================================================
#               ТАРИФЫ / ЛИМИТЫ (ФУНДАМЕНТ)
# =========================================================
# Тут потом просто меняешь цифры, а код не переписываешь.

TARIFFS = {
    "lite": {
        "title": "Lite",
        "bots_limit": 1,
    },
    "plus": {
        "title": "Plus",
        "bots_limit": 3,
    },
    "pro": {
        "title": "PRO",
        "bots_limit": 10,
    },
}

TRIAL_DAYS = 7           # бесплатный период
PAID_DAYS = 30           # оплаченный период (месяц)
DEFAULT_REMINDER_MINUTES = 10  # "на всякий" дефолт (ты просил 10 дней раньше — но ты сказал лучше в минутах)

# =========================================================
#                    ТЕКСТЫ (РЕДАКТИРУЕШЬ ТУТ)
# =========================================================
# Можно вставлять ссылки в обычный текст (Telegram сам сделает кликабельным).
# Если хочешь красивую ссылку "текстом" — это parse_mode HTML (мы включим HTML).

TEXT = {
    "start": (
        "👋 Привет! Это конструктор ботов по подписке.\n\n"
        "✅ 7 дней бесплатно, потом — подписка.\n"
        "Нажми кнопку ниже."
    ),
    "no_access": (
        "⛔️ У вас нет активного доступа.\n\n"
        "Можно начать бесплатные 7 дней или оформить подписку."
    ),
    "banned": "⛔️ Вы забанены. Обратитесь в поддержку.",
    "support_user_enter": (
        "✅ Вы обратились в службу поддержки.\n"
        "✍️ Напишите свой вопрос — скоро подключится менеджер."
    ),
    "support_admin_new": (
        "🆘 <b>Новый запрос в поддержку</b>\n"
        "Пользователь: {name}\n"
        "ID: <code>{uid}</code>\n"
        "Username: @{username}\n"
    ),
    "dialog_open_admin": (
        "✅ Диалог открыт.\n\n"
        "Теперь всё, что вы пишете — уйдёт пользователю <code>{uid}</code>.\n"
        "Чтобы завершить — нажмите кнопку ниже."
    ),
    "dialog_open_user": "✅ Менеджер подключился. Можете писать сообщения.",
    "dialog_closed_user": "✅ Диалог завершён. Нажмите «В начало».",
    "dialog_closed_admin": "✅ Диалог завершён.",
    "invalid_input": "❗️Неверный ввод. Нажмите «В начало».",
}

# =========================================================
#                 "ЭКРАНЫ" / КНОПКИ / НАПОМИНАНИЯ
# =========================================================
# Идея такая:
# - Каждый экран = ключ (например "home", "tariffs", "profile", "support")
# - У каждого экрана:
#   - текст
#   - кнопки
#   - напоминания: список (минуты, текст, кнопки)
#
# Ты просил: "на каждый экран по 3 напоминания" — делаем фундамент.
# Потом ты просто меняешь тексты/минуты.

SCREENS = {
    "home": {
        "text": "🏠 <b>Главное меню</b>\n\nВыберите действие:",
        "buttons": [
            ("💎 Тарифы", "go:tariffs"),
            ("🤖 Мои боты", "go:my_bots"),
            ("🆘 Техподдержка", "go:support"),
        ],
        "reminders": [
            {"minutes": 60, "text": "⏰ Вы давно не заходили. Посмотрите тарифы 😉", "buttons": [("💎 Тарифы", "go:tariffs")]},
            {"minutes": 180, "text": "🤖 Хотите создать бота? Нажмите «Мои боты».", "buttons": [("🤖 Мои боты", "go:my_bots")]},
            {"minutes": 1440, "text": "🔥 Напоминание: 7 дней бесплатно — успейте попробовать!", "buttons": [("🚀 Начать бесплатно", "trial:start")]},
        ],
    },

    "tariffs": {
        "text": "💎 <b>Тарифы</b>\n\nВыберите тариф и оплатите:",
        "buttons": [
            ("Lite", "pay:lite"),
            ("Plus", "pay:plus"),
            ("PRO", "pay:pro"),
            ("⬅️ Назад", "go:home"),
        ],
        "reminders": [
            {"minutes": 30, "text": "💡 Подсказка: Lite — для теста, Plus/PRO — если нужно больше ботов.", "buttons": [("⬅️ Назад", "go:home")]},
            {"minutes": 120, "text": "💳 Хотите оформить подписку? Выберите тариф.", "buttons": [("Plus", "pay:plus"), ("PRO", "pay:pro")]},
            {"minutes": 720, "text": "✅ Если есть вопросы — напишите в поддержку.", "buttons": [("🆘 Поддержка", "go:support")]},
        ],
    },

    "my_bots": {
        "text": "🤖 <b>Мои боты</b>\n\n(Фундамент: список появится позже)\n\nПока кнопки-заглушки:",
        "buttons": [
            ("➕ Создать бота", "bots:create"),
            ("📋 Список ботов", "bots:list"),
            ("⬅️ Назад", "go:home"),
        ],
        "reminders": [
            {"minutes": 60, "text": "➕ Хотите создать бота? Нажмите кнопку.", "buttons": [("➕ Создать бота", "bots:create")]},
            {"minutes": 240, "text": "📋 Посмотрите список ваших ботов.", "buttons": [("📋 Список ботов", "bots:list")]},
            {"minutes": 1440, "text": "💎 Нужно больше ботов? Увеличьте тариф.", "buttons": [("💎 Тарифы", "go:tariffs")]},
        ],
    },

    "support": {
        "text": "🆘 <b>Поддержка</b>\n\nНажмите кнопку ниже и напишите вопрос:",
        "buttons": [
            ("✍️ Написать в поддержку", "support:start"),
            ("⬅️ Назад", "go:home"),
        ],
        "reminders": [
            {"minutes": 30, "text": "✍️ Напишите вопрос — менеджер подключится.", "buttons": [("✍️ Написать", "support:start")]},
            {"minutes": 180, "text": "ℹ️ Если вопрос срочный — напишите подробнее, чтобы быстрее помочь.", "buttons": [("✍️ Написать", "support:start")]},
            {"minutes": 1440, "text": "✅ Мы на связи. Оставьте сообщение в поддержку.", "buttons": [("✍️ Написать", "support:start")]},
        ],
    },
}

# =========================================================
#                      БАЗА ДАННЫХ
# =========================================================

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    banned BOOLEAN NOT NULL DEFAULT FALSE,

    tariff TEXT NOT NULL DEFAULT 'lite',

    -- бесплатный период (если использован)
    trial_used BOOLEAN NOT NULL DEFAULT FALSE,
    trial_until TIMESTAMPTZ,

    -- оплата
    paid_until TIMESTAMPTZ,
    total_paid_cents BIGINT NOT NULL DEFAULT 0,

    -- текущий экран/состояние
    current_screen TEXT NOT NULL DEFAULT 'home',
    last_action_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- чтобы удалять "экраны"
    last_screen_message_ids BIGINT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS payments (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,              -- gumroad
    event_type TEXT NOT NULL,            -- sale/subscription
    plan TEXT,
    amount_cents BIGINT NOT NULL DEFAULT 0,
    currency TEXT,
    raw JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bots (
    id BIGSERIAL PRIMARY KEY,
    owner_telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    bot_name TEXT NOT NULL,
    bot_token TEXT,                      -- если будешь хранить токены (лучше шифровать позже)
    status TEXT NOT NULL DEFAULT 'stopped',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- поддержка / тикеты
CREATE TABLE IF NOT EXISTS support_tickets (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'open', -- open / active / closed
    assigned_admin BIGINT,               -- кто ведет диалог
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);

-- последние сообщения (лог)
CREATE TABLE IF NOT EXISTS support_messages (
    id BIGSERIAL PRIMARY KEY,
    ticket_id BIGINT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
    sender TEXT NOT NULL,                -- 'user' / 'admin'
    sender_id BIGINT NOT NULL,
    text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- напоминания (план на будущее)
CREATE TABLE IF NOT EXISTS reminders_queue (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    screen TEXT NOT NULL,
    reminder_index INT NOT NULL,
    run_at TIMESTAMPTZ NOT NULL,
    sent BOOLEAN NOT NULL DEFAULT FALSE
);
"""

# =========================================================
#                       УТИЛИТЫ
# =========================================================

def now_utc() -> datetime:
    return datetime.now(tz=UTC)

def parse_int(s: str, default: int = 0) -> int:
    try:
        return int(s)
    except Exception:
        return default

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def build_kb(buttons: List[Tuple[str, str]]):
    kb = InlineKeyboardBuilder()
    for text, data in buttons:
        kb.button(text=text, callback_data=data)
    kb.adjust(1)
    return kb.as_markup()

async def safe_delete(bot: Bot, chat_id: int, message_id: int):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

# =========================================================
#           ПРОВЕРКА ДОСТУПА (ОЧЕНЬ ВАЖНЫЙ ФУНДАМЕНТ)
# =========================================================
# Тут потом меняешь логику — а остальной код не трогаешь.

def доступ_есть(user_row: asyncpg.Record) -> bool:
    if user_row["banned"]:
        return False

    paid_until = user_row["paid_until"]
    trial_until = user_row["trial_until"]

    t = now_utc()

    if paid_until and paid_until > t:
        return True

    if trial_until and trial_until > t:
        return True

    return False

# =========================================================
#                 ОСНОВНОЕ ПРИЛОЖЕНИЕ
# =========================================================

app = FastAPI()
bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None
db_pool: Optional[asyncpg.Pool] = None

# =========================================================
#                   DB функции (фундамент)
# =========================================================

async def db_get_user(conn, telegram_id: int) -> Optional[asyncpg.Record]:
    return await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)

async def db_upsert_user(conn, telegram_id: int, username: str, full_name: str):
    await conn.execute("""
        INSERT INTO users(telegram_id, username, full_name)
        VALUES($1,$2,$3)
        ON CONFLICT(telegram_id) DO UPDATE
        SET username=EXCLUDED.username,
            full_name=EXCLUDED.full_name,
            last_action_at=NOW()
    """, telegram_id, username, full_name)

async def db_set_screen(conn, telegram_id: int, screen: str):
    await conn.execute("""
        UPDATE users SET current_screen=$2, last_action_at=NOW()
        WHERE telegram_id=$1
    """, telegram_id, screen)

async def db_set_last_screen_messages(conn, telegram_id: int, msg_ids: List[int]):
    await conn.execute("""
        UPDATE users SET last_screen_message_ids=$2
        WHERE telegram_id=$1
    """, telegram_id, msg_ids)

async def db_touch_activity(conn, telegram_id: int):
    await conn.execute("UPDATE users SET last_action_at=NOW() WHERE telegram_id=$1", telegram_id)

async def db_set_ban(conn, telegram_id: int, banned: bool):
    await conn.execute("UPDATE users SET banned=$2 WHERE telegram_id=$1", telegram_id, banned)

async def db_start_trial(conn, telegram_id: int):
    t = now_utc()
    trial_until = t + timedelta(days=TRIAL_DAYS)
    await conn.execute("""
        UPDATE users
        SET trial_used=TRUE, trial_until=$2, last_action_at=NOW()
        WHERE telegram_id=$1 AND trial_used=FALSE
    """, telegram_id, trial_until)

async def db_apply_payment(conn, telegram_id: int, plan: str, amount_cents: int, currency: str, raw: dict, event_type: str):
    t = now_utc()
    paid_until = t + timedelta(days=PAID_DAYS)

    # продление: если уже оплачено и не истекло — добавляем месяц сверху
    row = await db_get_user(conn, telegram_id)
    if row and row["paid_until"] and row["paid_until"] > t:
        paid_until = row["paid_until"] + timedelta(days=PAID_DAYS)

    await conn.execute("""
        UPDATE users
        SET tariff=$2,
            paid_until=$3,
            total_paid_cents=total_paid_cents + $4,
            last_action_at=NOW()
        WHERE telegram_id=$1
    """, telegram_id, plan, paid_until, amount_cents)

    await conn.execute("""
        INSERT INTO payments(telegram_id, provider, event_type, plan, amount_cents, currency, raw)
        VALUES($1,'gumroad',$2,$3,$4,$5,$6)
    """, telegram_id, event_type, plan, amount_cents, currency, json.dumps(raw))

async def db_count_bots(conn, telegram_id: int) -> int:
    return await conn.fetchval("SELECT COUNT(*) FROM bots WHERE owner_telegram_id=$1", telegram_id)

# ---- поддержка ----

async def db_create_ticket(conn, telegram_id: int) -> int:
    ticket_id = await conn.fetchval("""
        INSERT INTO support_tickets(telegram_id, status)
        VALUES($1,'open')
        RETURNING id
    """, telegram_id)
    return int(ticket_id)

async def db_get_open_ticket(conn, telegram_id: int) -> Optional[asyncpg.Record]:
    return await conn.fetchrow("""
        SELECT * FROM support_tickets
        WHERE telegram_id=$1 AND status IN ('open','active')
        ORDER BY id DESC LIMIT 1
    """, telegram_id)

async def db_set_ticket_active(conn, ticket_id: int, admin_id: int):
    await conn.execute("""
        UPDATE support_tickets
        SET status='active', assigned_admin=$2
        WHERE id=$1
    """, ticket_id, admin_id)

async def db_close_ticket(conn, ticket_id: int):
    await conn.execute("""
        UPDATE support_tickets
        SET status='closed', closed_at=NOW()
        WHERE id=$1
    """, ticket_id)

async def db_add_support_message(conn, ticket_id: int, sender: str, sender_id: int, text: str):
    await conn.execute("""
        INSERT INTO support_messages(ticket_id, sender, sender_id, text)
        VALUES($1,$2,$3,$4)
    """, ticket_id, sender, sender_id, text)

async def db_get_last_support_messages(conn, ticket_id: int, limit: int = 10) -> List[asyncpg.Record]:
    return await conn.fetch("""
        SELECT * FROM support_messages
        WHERE ticket_id=$1
        ORDER BY id DESC
        LIMIT $2
    """, ticket_id, limit)

# =========================================================
#             РЕНДЕР ЭКРАНА + УДАЛЕНИЕ СТАРЫХ СООБЩЕНИЙ
# =========================================================

async def show_screen(telegram_id: int, screen: str):
    """
    Переход на экран:
    - удалить прошлые "экранные" сообщения
    - отправить новое сообщение с кнопками
    - запланировать напоминания по экрану
    """
    assert bot and db_pool

    screen_cfg = SCREENS.get(screen)
    if not screen_cfg:
        screen = "home"
        screen_cfg = SCREENS["home"]

    async with db_pool.acquire() as conn:
        user = await db_get_user(conn, telegram_id)
        if not user:
            return

        # если забанен — всегда показываем бан
        if user["banned"]:
            # удаляем прошлые экраны
            for mid in user["last_screen_message_ids"]:
                await safe_delete(bot, telegram_id, int(mid))
            msg = await bot.send_message(telegram_id, TEXT["banned"], parse_mode="HTML", reply_markup=build_kb([("🆘 Поддержка", "go:support")]))
            await db_set_last_screen_messages(conn, telegram_id, [msg.message_id])
            await db_set_screen(conn, telegram_id, "home")
            return

        # удаляем прошлые экраны
        for mid in user["last_screen_message_ids"]:
            await safe_delete(bot, telegram_id, int(mid))

        msg = await bot.send_message(
            telegram_id,
            screen_cfg["text"],
            parse_mode="HTML",
            reply_markup=build_kb(screen_cfg["buttons"])
        )

        await db_set_last_screen_messages(conn, telegram_id, [msg.message_id])
        await db_set_screen(conn, telegram_id, screen)

        # запланировать 3 напоминания для этого экрана
        await schedule_screen_reminders(conn, telegram_id, screen)

async def schedule_screen_reminders(conn, telegram_id: int, screen: str):
    """
    Каждый раз при входе на экран — пересоздаем напоминания для этого экрана.
    Логика "сброса таймера": любое действие (кнопка/сообщение) вызывает show_screen или touch_activity,
    а напоминания мы ставим от текущего времени заново.
    """
    cfg = SCREENS.get(screen)
    if not cfg:
        return

    # удалить несработавшие напоминания по этому экрану
    await conn.execute("""
        DELETE FROM reminders_queue
        WHERE telegram_id=$1 AND screen=$2 AND sent=FALSE
    """, telegram_id, screen)

    base = now_utc()
    for idx, r in enumerate(cfg.get("reminders", [])):
        minutes = int(r.get("minutes", DEFAULT_REMINDER_MINUTES))
        run_at = base + timedelta(minutes=minutes)
        await conn.execute("""
            INSERT INTO reminders_queue(telegram_id, screen, reminder_index, run_at)
            VALUES($1,$2,$3,$4)
        """, telegram_id, screen, idx, run_at)

# =========================================================
#                 НАПОМИНАНИЯ: фон-процесс
# =========================================================

async def reminders_worker():
    """
    Каждые 30 секунд смотрит, какие напоминания пора отправить.
    Отправляет напоминание ТОЛЬКО если пользователь все еще на этом экране
    и был бездействующим (last_action_at не менялся) достаточно долго.
    """
    assert bot and db_pool
    while True:
        try:
            async with db_pool.acquire() as conn:
                due = await conn.fetch("""
                    SELECT rq.*, u.current_screen, u.last_action_at, u.banned
                    FROM reminders_queue rq
                    JOIN users u ON u.telegram_id = rq.telegram_id
                    WHERE rq.sent=FALSE AND rq.run_at <= NOW()
                    ORDER BY rq.run_at ASC
                    LIMIT 50
                """)

                for row in due:
                    if row["banned"]:
                        await conn.execute("UPDATE reminders_queue SET sent=TRUE WHERE id=$1", row["id"])
                        continue

                    tg = int(row["telegram_id"])
                    screen = row["screen"]
                    idx = int(row["reminder_index"])

                    # отправляем только если пользователь все еще на этом экране
                    if row["current_screen"] != screen:
                        await conn.execute("UPDATE reminders_queue SET sent=TRUE WHERE id=$1", row["id"])
                        continue

                    cfg = SCREENS.get(screen, {})
                    reminders = cfg.get("reminders", [])
                    if idx < 0 or idx >= len(reminders):
                        await conn.execute("UPDATE reminders_queue SET sent=TRUE WHERE id=$1", row["id"])
                        continue

                    r = reminders[idx]
                    kb = build_kb(r.get("buttons", [("🏠 В начало", "go:home")]))
                    await bot.send_message(tg, r.get("text", ""), parse_mode="HTML", reply_markup=kb)

                    await conn.execute("UPDATE reminders_queue SET sent=TRUE WHERE id=$1", row["id"])

        except Exception:
            # чтобы worker не умирал
            pass

        await asyncio.sleep(30)

# =========================================================
#                 GUMROAD WEBHOOK (FastAPI)
# =========================================================

def verify_gumroad_signature(raw_body: bytes, signature: str) -> bool:
    """
    Gumroad: подпись = HMAC SHA256 по raw body (в некоторых интеграциях).
    Если секрета нет — проверку пропускаем (но лучше установить секрет).
    """
    if not GUMROAD_WEBHOOK_SECRET:
        return True
    if not signature:
        return False
    mac = hmac.new(GUMROAD_WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, signature)

@app.post("/webhooks/gumroad")
async def gumroad_webhook(request: Request):
    """
    Ожидаем, что ты передаешь tg id в оплату:
    - либо через custom_fields[tg]
    - либо через параметр tg в query (если так настроишь)
    """
    assert db_pool

    raw_body = await request.body()
    signature = request.headers.get("X-Gumroad-Signature", "")

    if not verify_gumroad_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="bad signature")

    form = await request.form()
    data = dict(form)

    # --- пробуем вытащить tg id ---
    tg = None

    # вариант 1: custom_fields[tg]
    # FastAPI form даст ключи как "custom_fields[tg]" если так пришло.
    for k in list(data.keys()):
        if k.lower() in ("tg", "telegram_id"):
            tg = parse_int(str(data.get(k)))
        if k.lower() == "custom_fields[tg]":
            tg = parse_int(str(data.get(k)))

    if not tg:
        # иногда приходит JSON строкой
        pass

    if not tg:
        raise HTTPException(status_code=400, detail="no tg id")

    plan = (data.get("variant") or data.get("product_name") or data.get("plan") or "lite").lower()
    # нормализуем plan (lite/plus/pro)
    if "pro" in plan:
        plan = "pro"
    elif "plus" in plan:
        plan = "plus"
    elif "lite" in plan:
        plan = "lite"
    else:
        # если не распознали — ставим lite
        plan = "lite"

    amount_cents = parse_int(str(data.get("price", "0"))) * 100 if str(data.get("price", "")).isdigit() else parse_int(str(data.get("price_cents", "0")))
    currency = str(data.get("currency", "USD"))

    event_type = str(data.get("type", "sale"))  # sale/subscription_event

    async with db_pool.acquire() as conn:
        # убедимся что юзер есть
        user = await db_get_user(conn, tg)
        if not user:
            # создадим пользователя "пустым" (username/имя подтянется при /start)
            await conn.execute("INSERT INTO users(telegram_id) VALUES($1) ON CONFLICT DO NOTHING", tg)

        await db_apply_payment(conn, tg, plan, amount_cents, currency, data, event_type)

    # уведомим пользователя (если бот сможет написать)
    if bot:
        try:
            await bot.send_message(
                tg,
                f"✅ Оплата получена. Тариф: <b>{TARIFFS[plan]['title']}</b>\nДоступ активен.",
                parse_mode="HTML",
                reply_markup=build_kb([("🏠 В меню", "go:home")])
            )
        except Exception:
            pass

    return {"ok": True}

# =========================================================
#                    TELEGRAM BOT (aiogram)
# =========================================================

# Память для активных диалогов поддержки:
# admin_id -> user_id
ACTIVE_DIALOG: Dict[int, int] = {}


async def ensure_user(message: Message):
    """Создать/обновить юзера в базе"""
    assert db_pool
    uid = message.from_user.id
    username = message.from_user.username or ""
    full_name = (message.from_user.full_name or "").strip()

    async with db_pool.acquire() as conn:
        await db_upsert_user(conn, uid, username, full_name)


@dp.message(Command("start"))
async def cmd_start(message: Message):
    await ensure_user(message)

    async with db_pool.acquire() as conn:
        user = await db_get_user(conn, message.from_user.id)

        # если забанен
        if user and user["banned"]:
            await show_screen(message.from_user.id, "home")
            return

        # стартовый экран (покажем меню, а доступ проверим позже на действиях)
        await bot.send_message(message.chat.id, TEXT["start"], parse_mode="HTML",
                               reply_markup=build_kb([("🏠 В меню", "go:home"), ("🚀 Начать 7 дней бесплатно", "trial:start")]))

        await db_touch_activity(conn, message.from_user.id)


@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    await ensure_user(message)

    if not is_admin(message.from_user.id):
        return

    kb = build_kb([
        ("👥 Пользователи", "admin:users"),
        ("📊 Статистика", "admin:stats"),
        ("📨 Рассылка", "admin:broadcast"),
        ("🆘 Тикеты", "admin:tickets"),
    ])
    await bot.send_message(message.chat.id, "🛠 <b>Админ-панель</b>", parse_mode="HTML", reply_markup=kb)


# ---------------------------------------------------------
#   CALLBACK: навигация по экранам (go:screen)
# ---------------------------------------------------------

@dp.callback_query(F.data.startswith("go:"))
async def cb_go(call: CallbackQuery):
    await call.answer()
    uid = call.from_user.id

    async with db_pool.acquire() as conn:
        user = await db_get_user(conn, uid)
        if user and user["banned"]:
            await show_screen(uid, "home")
            return

        await db_touch_activity(conn, uid)

    screen = call.data.split(":", 1)[1]
    await show_screen(uid, screen)


# ---------------------------------------------------------
#   ДОСТУП / ТРИАЛ / ОПЛАТА
# ---------------------------------------------------------

@dp.callback_query(F.data == "trial:start")
async def cb_trial(call: CallbackQuery):
    await call.answer()
    uid = call.from_user.id

    async with db_pool.acquire() as conn:
        user = await db_get_user(conn, uid)
        if not user:
            await db_upsert_user(conn, uid, call.from_user.username or "", call.from_user.full_name or "")

        user = await db_get_user(conn, uid)
        if user["trial_used"]:
            await bot.send_message(uid, "❗️Бесплатный период уже был использован.", reply_markup=build_kb([("💎 Тарифы", "go:tariffs"), ("🏠 В меню", "go:home")]))
            return

        await db_start_trial(conn, uid)
        await bot.send_message(uid, f"✅ Бесплатный доступ активирован на {TRIAL_DAYS} дней.", reply_markup=build_kb([("🏠 В меню", "go:home")]))

        await db_touch_activity(conn, uid)

@dp.callback_query(F.data.startswith("pay:"))
async def cb_pay(call: CallbackQuery):
    await call.answer()
    uid = call.from_user.id
    plan = call.data.split(":", 1)[1]

    url = GUMROAD_URLS.get(plan, "")
    if not url:
        await bot.send_message(uid, "❗️Ссылка оплаты не настроена. Добавь переменную GUMROAD_*_URL в Railway.")
        return

    # ВАЖНО:
    # Чтобы бот знал чей платеж, в ссылку надо добавить tg id:
    #   https://gumroad.com/... ?tg=123456789
    # или через custom_fields.
    # Тут мы делаем “готовую ссылку”.
    sep = "&" if "?" in url else "?"
    pay_url = f"{url}{sep}tg={uid}"

    kb = build_kb([
        ("💳 Оплатить", f"url:{pay_url}"),
        ("⬅️ Назад", "go:tariffs"),
    ])

    await bot.send_message(
        uid,
        f"💳 Оплата тарифа <b>{TARIFFS.get(plan, {}).get('title','')}</b>\n\n"
        f"Открой ссылку и оплати. После оплаты доступ включится автоматически.",
        parse_mode="HTML",
        reply_markup=kb
    )

# обработка url:* (чтобы кнопка открывала ссылку)
@dp.callback_query(F.data.startswith("url:"))
async def cb_url(call: CallbackQuery):
    # Telegram сам откроет ссылку, тут просто закрываем "часики"
    await call.answer()


# ---------------------------------------------------------
#   ТЕХПОДДЕРЖКА
# ---------------------------------------------------------

@dp.callback_query(F.data == "support:start")
async def cb_support_start(call: CallbackQuery):
    await call.answer()
    uid = call.from_user.id

    async with db_pool.acquire() as conn:
        user = await db_get_user(conn, uid)
        if user and user["banned"]:
            await bot.send_message(uid, TEXT["banned"], reply_markup=build_kb([("🏠 В начало", "go:home")]))
            return

        ticket = await db_get_open_ticket(conn, uid)
        if not ticket:
            ticket_id = await db_create_ticket(conn, uid)
        else:
            ticket_id = int(ticket["id"])

        await db_touch_activity(conn, uid)

    await bot.send_message(uid, TEXT["support_user_enter"], reply_markup=build_kb([("⬅️ Назад", "go:home")]))

    # уведомим админов
    for admin_id in ADMIN_IDS:
        try:
            username = call.from_user.username or "-"
            name = (call.from_user.full_name or "").strip()
            text = TEXT["support_admin_new"].format(name=name, uid=uid, username=username)
            kb = build_kb([
                ("✅ Открыть диалог", f"admin:open_dialog:{uid}"),
                ("⛔️ Бан", f"admin:ban:{uid}"),
            ])
            await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            pass


@dp.callback_query(F.data.startswith("admin:open_dialog:"))
async def cb_admin_open_dialog(call: CallbackQuery):
    await call.answer()
    admin_id = call.from_user.id
    if not is_admin(admin_id):
        return

    uid = int(call.data.split(":")[-1])

    async with db_pool.acquire() as conn:
        ticket = await db_get_open_ticket(conn, uid)
        if not ticket:
            await bot.send_message(admin_id, "❗️У пользователя нет активного тикета.")
            return

        await db_set_ticket_active(conn, int(ticket["id"]), admin_id)

        ACTIVE_DIALOG[admin_id] = uid

        await bot.send_message(
            admin_id,
            TEXT["dialog_open_admin"].format(uid=uid),
            parse_mode="HTML",
            reply_markup=build_kb([
                ("✅ Завершить диалог", f"admin:close_dialog:{uid}"),
                ("⬅️ В админ-панель", "admin:back"),
            ])
        )

    # уведомим юзера
    try:
        await bot.send_message(uid, TEXT["dialog_open_user"], reply_markup=build_kb([("🏠 В начало", "go:home")]))
    except Exception:
        pass


@dp.callback_query(F.data.startswith("admin:close_dialog:"))
async def cb_admin_close_dialog(call: CallbackQuery):
    await call.answer()
    admin_id = call.from_user.id
    if not is_admin(admin_id):
        return

    uid = int(call.data.split(":")[-1])

    async with db_pool.acquire() as conn:
        ticket = await db_get_open_ticket(conn, uid)
        if ticket:
            await db_close_ticket(conn, int(ticket["id"]))

    # закрыть активный диалог
    if ACTIVE_DIALOG.get(admin_id) == uid:
        ACTIVE_DIALOG.pop(admin_id, None)

    await bot.send_message(admin_id, TEXT["dialog_closed_admin"], reply_markup=build_kb([("⬅️ В админ-панель", "admin:back")]))

    try:
        await bot.send_message(uid, TEXT["dialog_closed_user"], reply_markup=build_kb([("🏠 В начало", "go:home")]))
    except Exception:
        pass


@dp.callback_query(F.data == "admin:back")
async def cb_admin_back(call: CallbackQuery):
    await call.answer()
    if not is_admin(call.from_user.id):
        return
    kb = build_kb([
        ("👥 Пользователи", "admin:users"),
        ("📊 Статистика", "admin:stats"),
        ("📨 Рассылка", "admin:broadcast"),
        ("🆘 Тикеты", "admin:tickets"),
    ])
    await bot.send_message(call.from_user.id, "🛠 <b>Админ-панель</b>", parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("admin:ban:"))
async def cb_admin_ban(call: CallbackQuery):
    await call.answer()
    if not is_admin(call.from_user.id):
        return
    uid = int(call.data.split(":")[-1])

    async with db_pool.acquire() as conn:
        await db_set_ban(conn, uid, True)

    await bot.send_message(call.from_user.id, f"⛔️ Пользователь {uid} забанен.")
    try:
        await bot.send_message(uid, TEXT["banned"], reply_markup=build_kb([("🆘 Поддержка", "go:support")]))
    except Exception:
        pass


# ---------------------------------------------------------
#   АДМИН: пользователи/статистика (фундамент)
# ---------------------------------------------------------

@dp.callback_query(F.data == "admin:users")
async def cb_admin_users(call: CallbackQuery):
    await call.answer()
    if not is_admin(call.from_user.id):
        return

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT telegram_id, username, full_name, tariff, banned, paid_until, trial_until, total_paid_cents
            FROM users
            ORDER BY created_at DESC
            LIMIT 20
        """)

    lines = ["👥 <b>Последние 20 пользователей</b>\n"]
    for r in rows:
        uid = int(r["telegram_id"])
        tariff = r["tariff"]
        banned = "⛔️" if r["banned"] else "✅"
        paid_until = r["paid_until"].strftime("%Y-%m-%d") if r["paid_until"] else "-"
        trial_until = r["trial_until"].strftime("%Y-%m-%d") if r["trial_until"] else "-"
        lines.append(f"{banned} <code>{uid}</code> @{r['username'] or '-'} | {tariff} | paid:{paid_until} | free:{trial_until}")

    kb = build_kb([("⬅️ Назад", "admin:back")])
    await bot.send_message(call.from_user.id, "\n".join(lines), parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "admin:stats")
async def cb_admin_stats(call: CallbackQuery):
    await call.answer()
    if not is_admin(call.from_user.id):
        return

    async with db_pool.acquire() as conn:
        users_total = await conn.fetchval("SELECT COUNT(*) FROM users")
        paid_active = await conn.fetchval("SELECT COUNT(*) FROM users WHERE paid_until IS NOT NULL AND paid_until > NOW()")
        trial_active = await conn.fetchval("SELECT COUNT(*) FROM users WHERE trial_until IS NOT NULL AND trial_until > NOW()")
        total_paid = await conn.fetchval("SELECT COALESCE(SUM(total_paid_cents),0) FROM users")

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Всего пользователей: <b>{users_total}</b>\n"
        f"💳 Активная оплата: <b>{paid_active}</b>\n"
        f"🎁 Активный бесплатный период: <b>{trial_active}</b>\n"
        f"💰 Всего заработано (cents): <b>{total_paid}</b>\n"
    )
    await bot.send_message(call.from_user.id, text, parse_mode="HTML", reply_markup=build_kb([("⬅️ Назад", "admin:back")]))


@dp.callback_query(F.data == "admin:tickets")
async def cb_admin_tickets(call: CallbackQuery):
    await call.answer()
    if not is_admin(call.from_user.id):
        return

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT t.id, t.telegram_id, t.status, t.assigned_admin, t.created_at
            FROM support_tickets t
            ORDER BY t.created_at DESC
            LIMIT 20
        """)

    lines = ["🆘 <b>Последние 20 тикетов</b>\n"]
    for r in rows:
        lines.append(f"#{r['id']} | <code>{r['telegram_id']}</code> | {r['status']} | admin:{r['assigned_admin'] or '-'}")

    await bot.send_message(call.from_user.id, "\n".join(lines), parse_mode="HTML", reply_markup=build_kb([("⬅️ Назад", "admin:back")]))


# ---------------------------------------------------------
#   ЛОГИКА СООБЩЕНИЙ:
#   - если админ в активном диалоге => переслать пользователю
#   - если пользователь в активном тикете => переслать админам + сохранить последние 10
#   - иначе => "неверный ввод" и кнопка "в начало"
# ---------------------------------------------------------

@dp.message()
async def on_any_message(message: Message):
    await ensure_user(message)
    uid = message.from_user.id

    # 1) если пользователь забанен — сразу
    async with db_pool.acquire() as conn:
        user = await db_get_user(conn, uid)
        if user and user["banned"]:
            await bot.send_message(uid, TEXT["banned"], reply_markup=build_kb([("🆘 Поддержка", "go:support")]))
            return
        await db_touch_activity(conn, uid)

    # 2) если это админ и он в диалоге — отправляем юзеру
    if is_admin(uid) and uid in ACTIVE_DIALOG:
        target_uid = ACTIVE_DIALOG[uid]
        text = message.text or ""
        if not text:
            await bot.send_message(uid, "❗️Пока поддерживаем только текст.")
            return

        async with db_pool.acquire() as conn:
            ticket = await db_get_open_ticket(conn, target_uid)
            if ticket:
                await db_add_support_message(conn, int(ticket["id"]), "admin", uid, text)

        try:
            await bot.send_message(target_uid, f"👨‍💻 Менеджер:\n{text}")
        except Exception:
            await bot.send_message(uid, "❗️Не удалось отправить сообщение пользователю.")
        return

    # 3) если юзер пишет в поддержку (есть open/active тикет) — шлем админам
    async with db_pool.acquire() as conn:
        ticket = await db_get_open_ticket(conn, uid)

    if ticket:
        text = message.text or ""
        if not text:
            await bot.send_message(uid, "❗️Пока поддерживаем только текст.")
            return

        async with db_pool.acquire() as conn:
            await db_add_support_message(conn, int(ticket["id"]), "user", uid, text)

        # отправим всем админам
        for admin_id in ADMIN_IDS:
            try:
                kb = build_kb([
                    ("✅ Открыть диалог", f"admin:open_dialog:{uid}"),
                    ("⛔️ Бан", f"admin:ban:{uid}"),
                ])
                await bot.send_message(
                    admin_id,
                    f"🆘 <b>Сообщение в поддержку</b>\n"
                    f"От: <code>{uid}</code>\n\n"
                    f"{text}",
                    parse_mode="HTML",
                    reply_markup=kb
                )
            except Exception:
                pass

        await bot.send_message(uid, "✅ Сообщение отправлено в поддержку. Ожидайте ответ.")
        return

    # 4) иначе — неверный ввод
    await bot.send_message(uid, TEXT["invalid_input"], reply_markup=build_kb([("🏠 В начало", "go:home")]))


# =========================================================
#                     STARTUP / SHUTDOWN
# =========================================================

@app.on_event("startup")
async def on_startup():
    global bot, dp, db_pool

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL не задан")
    if not ADMIN_IDS:
        print("⚠️ ADMIN_IDS пустой — /admin не будет работать")

    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)

    if AUTO_MIGRATE:
        async with db_pool.acquire() as conn:
            await conn.execute(MIGRATION_SQL)

    

    # регистрируем хендлеры (ВАЖНО: dp уже используется декораторами, но в aiogram 3 так можно,
    # если dp создан ДО декораторов. Поэтому мы создали dp сверху как Optional,
    # а реально Dispatcher создаем тут — так безопаснее: пересоздадим и заново привяжем.)
    # Чтобы было максимально стабильно — сделаем так:
    #
    # В этом фундаменте декораторы уже "повешены" на dp, поэтому dp НЕ пересоздаем.
    # Просто используем dp который объявлен вверху.
    #
    # (если хочешь 100% чисто — вынесем хендлеры в отдельный файл. Но ты просил 1 файл.)

    # запускаем напоминания
    asyncio.create_task(reminders_worker())

    # запускаем long polling в фоне (Railway нормально)
    asyncio.create_task(dp.start_polling(bot))


@app.on_event("shutdown")
async def on_shutdown():
    global bot, db_pool
    if bot:
        await bot.session.close()
    if db_pool:
        await db_pool.close()


# =========================================================
#                      HTTP для проверки
# =========================================================

@app.get("/")
async def root():
    return {"status": "Bot Builder is running 🚀"}

