import os
import json
import hmac
import hashlib
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Tuple

import asyncpg
from fastapi import FastAPI, Request, HTTPException

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties


# ============================================================
# 1) НАСТРОЙКИ / ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (Railway -> Variables)
# ============================================================

UTC = timezone.utc

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# ВАЖНО: ADMIN_IDS = "123,456" (через запятую)
ADMIN_IDS = set(
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
)

# Секрет для нашего webhook (чтоб никто кроме Gumroad/тебя не дёргал endpoint)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

# Если хочешь проверять подпись Gumroad — задай секрет Gumroad (опционально)
GUMROAD_WEBHOOK_SECRET = os.getenv("GUMROAD_WEBHOOK_SECRET", "").strip()

# Публичный URL сервиса Railway (нужно для ссылок в тексте, и просто полезно)
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip()

# Ссылки на оплату (позже заменишь на реальные)
GUMROAD_URLS = {
    "lite": os.getenv("GUMROAD_LITE_URL", "").strip(),
    "plus": os.getenv("GUMROAD_PLUS_URL", "").strip(),
    "pro": os.getenv("GUMROAD_PRO_URL", "").strip(),
}

AUTO_MIGRATE = os.getenv("AUTO_MIGRATE", "1").strip() == "1"

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не задан в Railway Variables")
if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL не задан в Railway Variables")
if not WEBHOOK_SECRET:
    # Можно оставить пустым, но НЕ советую. Безопасность хуже.
    print("⚠️ WEBHOOK_SECRET пустой — webhook небезопасен")


# ============================================================
# 2) ТАРИФЫ / ЛИМИТЫ (ФУНДАМЕНТ) — МЕНЯЕШЬ ЦИФРЫ, КОД НЕ ТРОГАЕШЬ
# ============================================================

# Важно: лимиты — это фундамент. Потом просто меняешь цифры и тексты.
TARIFFS = {
    "free": {
        "title": "Бесплатный",
        "bots_limit": 0,                 # сколько ботов можно создать
        "messages_per_day_limit": 20,    # сообщений в день (пример)
        "screens_limit": 10,             # сколько “экранов/шагов” можно настроить (пример)
        "price_text": "0$",
    },
    "lite": {
        "title": "Lite",
        "bots_limit": 1,
        "messages_per_day_limit": 300,
        "screens_limit": 50,
        "price_text": "9$ / месяц",
    },
    "plus": {
        "title": "Plus",
        "bots_limit": 3,
        "messages_per_day_limit": 1500,
        "screens_limit": 200,
        "price_text": "19$ / месяц",
    },
    "pro": {
        "title": "PRO",
        "bots_limit": 10,
        "messages_per_day_limit": 10000,
        "screens_limit": 999,
        "price_text": "49$ / месяц",
    },
}

# Пробный период (7 дней)
ПРОБНЫЕ_ДНИ = 7

# Подписка на месяц (30 дней) — от даты покупки
ПЛАТНЫЕ_ДНИ = 30


# ============================================================
# 3) ТЕКСТЫ / “ЭКРАНЫ” (ФУНДАМЕНТ)
#    Тут ты потом спокойно меняешь тексты, вставляешь ссылки, кнопки.
#    HTML включён. Можно: <b>, <i>, <a href="...">Ссылка</a>
# ============================================================

TEXT_START = (
    "👋 <b>Добро пожаловать в конструктор ботов</b>\n\n"
    "Выберите действие ниже."
)

TEXT_TARIFFS = (
    "💳 <b>Тарифы</b>\n\n"
    "Выберите подходящий тариф.\n\n"
    "Можно вставлять ссылки прямо в текст:\n"
    "Например: <a href=\"https://example.com\">Видео-инструкция</a>"
)

TEXT_SUPPORT = (
    "✅ <b>Вы обратились в службу поддержки.</b>\n"
    "✍️ Напишите свой вопрос — скоро подключится менеджер."
)

TEXT_BANNED = "⛔ Вы забанены. Обратитесь в поддержку."


# ============================================================
# 4) НАПОМИНАНИЯ ПРИ БЕЗДЕЙСТВИИ (ФУНДАМЕНТ)
#    Ты сам потом меняешь минуты и текст.
#    Для каждого “экрана” можно свои напоминания.
# ============================================================

# Формат: экран -> список напоминаний (минуты, текст, кнопка)
REMINDERS_CONFIG = {
    "start": [
        (60, "⏳ Вы ещё здесь? Нажмите кнопку ниже, чтобы продолжить.", "🔁 Вернуться в меню"),
        (180, "👀 Напоминаю: вы можете выбрать тариф и начать.", "💳 Тарифы"),
        (1440, "🔥 Не забудьте: пробный период заканчивается, успейте оформить подписку.", "💳 Тарифы"),
    ],
    "tariffs": [
        (30, "💡 Если есть вопросы по тарифам — напишите в поддержку.", "🛠 Поддержка"),
        (120, "⚡ Хотите больше возможностей? Выберите тариф.", "✅ Выбрать тариф"),
        (600, "⏳ Вы всё ещё выбираете тариф. Нужна помощь?", "🛠 Поддержка"),
    ],
    "support": [
        (30, "✍️ Напишите сообщение — менеджер увидит и ответит.", "⬅️ Назад"),
        (120, "Мы на связи. Напишите вопрос одним сообщением.", "⬅️ Назад"),
        (600, "Если вопрос не актуален — нажмите «Назад».", "⬅️ Назад"),
    ],
}


# ============================================================
# 5) БАЗА ДАННЫХ (ФУНДАМЕНТ ТАБЛИЦ)
#    Создаём сразу всё нужное, чтобы потом не переписывать.
# ============================================================

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- статус
    is_banned BOOLEAN NOT NULL DEFAULT FALSE,

    -- тариф/подписка
    plan TEXT NOT NULL DEFAULT 'free',
    trial_until TIMESTAMPTZ,
    paid_until TIMESTAMPTZ,

    -- деньги (статистика)
    total_paid_cents BIGINT NOT NULL DEFAULT 0,
    last_payment_at TIMESTAMPTZ,

    -- активность и интерфейс
    last_action_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    current_screen TEXT NOT NULL DEFAULT 'start',
    last_screen_message_id BIGINT,
    reminder_message_ids JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- поддержка
    support_state TEXT NOT NULL DEFAULT 'none'  -- none | waiting_user | in_dialog
);

CREATE TABLE IF NOT EXISTS payments (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'gumroad',
    provider_payment_id TEXT,
    plan TEXT,
    amount_cents BIGINT NOT NULL DEFAULT 0,
    currency TEXT,
    raw JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bots (
    id BIGSERIAL PRIMARY KEY,
    owner_telegram_id BIGINT NOT NULL,
    bot_name TEXT NOT NULL,
    bot_token TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- лимиты (сколько сообщений/действий сделал пользователь за день)
CREATE TABLE IF NOT EXISTS daily_usage (
    telegram_id BIGINT NOT NULL,
    day DATE NOT NULL,
    messages_count INT NOT NULL DEFAULT 0,
    PRIMARY KEY (telegram_id, day)
);

-- переписка поддержки (храним последние сообщения)
CREATE TABLE IF NOT EXISTS support_threads (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    is_open BOOLEAN NOT NULL DEFAULT TRUE,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS support_messages (
    id BIGSERIAL PRIMARY KEY,
    thread_id BIGINT NOT NULL REFERENCES support_threads(id) ON DELETE CASCADE,
    sender TEXT NOT NULL, -- 'user' | 'admin'
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


# ============================================================
# 6) FASTAPI + AIOGRAM (ВАЖНО: dp создаём ДО ДЕКОРАТОРОВ!)
# ============================================================

app = FastAPI()

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")  # ✅ aiogram 3.7+ правильный способ
)
dp = Dispatcher()

db_pool: Optional[asyncpg.Pool] = None


# ============================================================
# 7) ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (ФУНДАМЕНТ ЛОГИКИ)
# ============================================================

def now_utc() -> datetime:
    return datetime.now(tz=UTC)

def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMIN_IDS

async def db() -> asyncpg.Pool:
    global db_pool
    if db_pool is None:
        raise RuntimeError("DB pool не инициализирован")
    return db_pool

async def ensure_user(tg: Message | CallbackQuery) -> Dict[str, Any]:
    """Создаёт пользователя если нет, и всегда обновляет last_action_at."""
    telegram_id = tg.from_user.id
    username = tg.from_user.username
    first_name = tg.from_user.first_name

    pool = await db()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id=$1",
            telegram_id
        )
        if not user:
            trial_until = now_utc() + timedelta(days=ПРОБНЫЕ_ДНИ)
            await conn.execute(
                """
                INSERT INTO users (telegram_id, username, first_name, trial_until, plan)
                VALUES ($1,$2,$3,$4,'free')
                """,
                telegram_id, username, first_name, trial_until
            )
            user = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)

        # обновим активность
        await conn.execute(
            "UPDATE users SET last_action_at=now() WHERE telegram_id=$1",
            telegram_id
        )

        return dict(user)

def есть_доступ(user: Dict[str, Any]) -> bool:
    """
    ГЛАВНАЯ ФУНКЦИЯ ПРОВЕРКИ ДОСТУПА (ФУНДАМЕНТ)
    Тут вся логика — чтобы потом не переписывать весь код.
    """
    if user.get("is_banned"):
        return False

    t = now_utc()
    trial_until = user.get("trial_until")
    paid_until = user.get("paid_until")

    # trial_until / paid_until из asyncpg может быть datetime уже
    if trial_until and trial_until > t:
        return True
    if paid_until and paid_until > t:
        return True

    return False

async def set_screen(telegram_id: int, screen: str) -> None:
    pool = await db()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET current_screen=$2 WHERE telegram_id=$1",
            telegram_id, screen
        )

async def safe_delete(chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass

async def clear_old_ui(user: Dict[str, Any], chat_id: int) -> None:
    """Удаляем прошлый “экран” и прошлые напоминания, чтобы интерфейс был чистый."""
    last_screen_message_id = user.get("last_screen_message_id")
    if last_screen_message_id:
        await safe_delete(chat_id, int(last_screen_message_id))

    reminder_ids = user.get("reminder_message_ids") or []
    # reminder_message_ids хранится как jsonb массив
    if isinstance(reminder_ids, str):
        try:
            reminder_ids = json.loads(reminder_ids)
        except Exception:
            reminder_ids = []
    for mid in reminder_ids:
        try:
            await safe_delete(chat_id, int(mid))
        except Exception:
            pass

    pool = await db()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET reminder_message_ids='[]'::jsonb WHERE telegram_id=$1",
            user["telegram_id"]
        )

async def store_screen_message_id(telegram_id: int, message_id: int) -> None:
    pool = await db()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET last_screen_message_id=$2 WHERE telegram_id=$1",
            telegram_id, message_id
        )

async def add_reminder_message_id(telegram_id: int, message_id: int) -> None:
    pool = await db()
    async with pool.acquire() as conn:
        # Добавим в JSON массив
        await conn.execute(
            """
            UPDATE users
            SET reminder_message_ids = reminder_message_ids || to_jsonb($2::bigint)
            WHERE telegram_id=$1
            """,
            telegram_id, message_id
        )

async def inc_daily_messages(telegram_id: int) -> None:
    """Фундамент счётчика сообщений для лимитов."""
    today = now_utc().date()
    pool = await db()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO daily_usage (telegram_id, day, messages_count)
            VALUES ($1,$2,1)
            ON CONFLICT (telegram_id, day)
            DO UPDATE SET messages_count = daily_usage.messages_count + 1
            """,
            telegram_id, today
        )

async def get_daily_messages(telegram_id: int) -> int:
    today = now_utc().date()
    pool = await db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT messages_count FROM daily_usage WHERE telegram_id=$1 AND day=$2",
            telegram_id, today
        )
        return int(row["messages_count"]) if row else 0

async def get_user_by_id(telegram_id: int) -> Optional[Dict[str, Any]]:
    pool = await db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)
        return dict(row) if row else None

async def update_user_subscription(telegram_id: int, plan: str, add_days: int, amount_cents: int) -> None:
    """Обновляем подписку: платно до +30 дней от СЕЙЧАС или от paid_until если он ещё живой."""
    pool = await db()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)
        if not user:
            # если webhook пришёл раньше чем пользователь нажал /start — создадим
            trial_until = now_utc() + timedelta(days=ПРОБНЫЕ_ДНИ)
            await conn.execute(
                "INSERT INTO users (telegram_id, trial_until, plan) VALUES ($1,$2,'free')",
                telegram_id, trial_until
            )
            user = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)

        cur_paid_until = user["paid_until"]
        base = cur_paid_until if (cur_paid_until and cur_paid_until > now_utc()) else now_utc()
        new_paid_until = base + timedelta(days=add_days)

        await conn.execute(
            """
            UPDATE users
            SET plan=$2,
                paid_until=$3,
                total_paid_cents=total_paid_cents + $4,
                last_payment_at=now()
            WHERE telegram_id=$1
            """,
            telegram_id, plan, new_paid_until, amount_cents
        )

async def ban_user(telegram_id: int, value: bool) -> None:
    pool = await db()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET is_banned=$2 WHERE telegram_id=$1",
            telegram_id, value
        )


# ============================================================
# 8) КНОПКИ / КЛАВИАТУРЫ (ФУНДАМЕНТ)
# ============================================================

def kb_main() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Тарифы", callback_data="screen:tariffs")
    kb.button(text="🛠 Поддержка", callback_data="screen:support")
    kb.button(text="👤 Профиль", callback_data="screen:profile")
    kb.adjust(2, 1)
    return kb

def kb_tariffs() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="Lite", callback_data="buy:lite")
    kb.button(text="Plus", callback_data="buy:plus")
    kb.button(text="PRO", callback_data="buy:pro")
    kb.button(text="⬅️ Назад", callback_data="screen:start")
    kb.adjust(3, 1)
    return kb

def kb_support_back() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="screen:start")
    kb.adjust(1)
    return kb

def kb_profile(user: Dict[str, Any]) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Тарифы", callback_data="screen:tariffs")
    kb.button(text="🛠 Поддержка", callback_data="screen:support")
    kb.button(text="⬅️ Назад", callback_data="screen:start")
    kb.adjust(2, 1)
    return kb

def kb_admin_panel() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data="admin:stats")
    kb.button(text="🔎 Пользователь по ID", callback_data="admin:ask_user_id")
    kb.adjust(1, 1)
    return kb

def kb_admin_user(telegram_id: int, banned: bool) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="💬 Открыть диалог", callback_data=f"admin:open_dialog:{telegram_id}")
    kb.button(text=("✅ Разбан" if banned else "⛔ Бан"), callback_data=f"admin:ban:{telegram_id}")
    kb.button(text="⬅️ В админ-панель", callback_data="admin:panel")
    kb.adjust(1, 1, 1)
    return kb

def kb_admin_dialog(telegram_id: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Завершить диалог", callback_data=f"admin:close_dialog:{telegram_id}")
    kb.button(text="⬅️ В админ-панель", callback_data="admin:panel")
    kb.adjust(1, 1)
    return kb


# ============================================================
# 9) РЕНДЕР ЭКРАНОВ (главная фишка: удаляем прошлое и рисуем новое)
# ============================================================

async def show_screen(chat_id: int, user: Dict[str, Any], screen: str) -> None:
    # если забанен — показываем бан и всё
    if user.get("is_banned"):
        await clear_old_ui(user, chat_id)
        m = await bot.send_message(chat_id, TEXT_BANNED)
        await store_screen_message_id(user["telegram_id"], m.message_id)
        await set_screen(user["telegram_id"], "banned")
        return

    await clear_old_ui(user, chat_id)
    await set_screen(user["telegram_id"], screen)

    if screen == "start":
        m = await bot.send_message(chat_id, TEXT_START, reply_markup=kb_main().as_markup())
        await store_screen_message_id(user["telegram_id"], m.message_id)

    elif screen == "tariffs":
        # собираем текст тарифов красиво
        lines = [TEXT_TARIFFS, ""]
        for k in ["lite", "plus", "pro"]:
            t = TARIFFS[k]
            lines.append(
                f"• <b>{t['title']}</b> — {t['price_text']}\n"
                f"  Ботов: <b>{t['bots_limit']}</b> | Сообщ/день: <b>{t['messages_per_day_limit']}</b>"
            )
        m = await bot.send_message(chat_id, "\n".join(lines), reply_markup=kb_tariffs().as_markup())
        await store_screen_message_id(user["telegram_id"], m.message_id)

    elif screen == "support":
        # ставим режим ожидания вопроса
        pool = await db()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET support_state='waiting_user' WHERE telegram_id=$1",
                user["telegram_id"]
            )

        m = await bot.send_message(chat_id, TEXT_SUPPORT, reply_markup=kb_support_back().as_markup())
        await store_screen_message_id(user["telegram_id"], m.message_id)

        # уведомляем админа, что пользователь открыл поддержку
        for admin_id in ADMIN_IDS:
            try:
                kb = InlineKeyboardBuilder()
                kb.button(text="💬 Открыть диалог", callback_data=f"admin:open_dialog:{user['telegram_id']}")
                kb.button(text="👤 Профиль", callback_data=f"admin:user:{user['telegram_id']}")
                kb.adjust(1, 1)
                await bot.send_message(
                    admin_id,
                    f"🛠 <b>Новый запрос в поддержку</b>\n"
                    f"ID: <code>{user['telegram_id']}</code>\n"
                    f"Имя: {user.get('first_name') or '-'}\n"
                    f"Юзернейм: @{user.get('username')}" if user.get("username") else
                    f"🛠 <b>Новый запрос в поддержку</b>\nID: <code>{user['telegram_id']}</code>",
                    reply_markup=kb.as_markup()
                )
            except Exception:
                pass

    elif screen == "profile":
        # показываем статус подписки
        t = now_utc()
        trial_until = user.get("trial_until")
        paid_until = user.get("paid_until")
        plan = user.get("plan", "free")

        status_lines = [f"👤 <b>Профиль</b>\nID: <code>{user['telegram_id']}</code>"]
        status_lines.append(f"Тариф: <b>{TARIFFS.get(plan, TARIFFS['free'])['title']}</b>")

        if paid_until and paid_until > t:
            status_lines.append(f"✅ Оплачено до: <b>{paid_until.strftime('%Y-%m-%d %H:%M')}</b> (UTC)")
        elif trial_until and trial_until > t:
            status_lines.append(f"🎁 Пробный доступ до: <b>{trial_until.strftime('%Y-%m-%d %H:%M')}</b> (UTC)")
        else:
            status_lines.append("❌ Доступ не активен. Оформите подписку.")

        m = await bot.send_message(chat_id, "\n".join(status_lines), reply_markup=kb_profile(user).as_markup())
        await store_screen_message_id(user["telegram_id"], m.message_id)

    else:
        m = await bot.send_message(chat_id, "Неизвестный экран.")
        await store_screen_message_id(user["telegram_id"], m.message_id)


# ============================================================
# 10) НАПОМИНАНИЯ ФОН (проверяем бездействие и шлём нужные сообщения)
# ============================================================

async def reminders_worker():
    while True:
        try:
            pool = await db()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT telegram_id, current_screen, last_action_at, is_banned FROM users"
                )
            now = now_utc()

            for r in rows:
                if r["is_banned"]:
                    continue

                screen = r["current_screen"]
                last_action_at = r["last_action_at"]
                tg_id = int(r["telegram_id"])

                if screen not in REMINDERS_CONFIG:
                    continue

                minutes_inactive = int((now - last_action_at).total_seconds() // 60)

                # логика простая: если ровно прошло N минут (или чуть больше), шлём напоминание
                # Чтобы не спамить — мы будем слать, если minutes_inactive == N (плюс окно 2 мин)
                for (min_need, text, btn_text) in REMINDERS_CONFIG[screen]:
                    if min_need <= minutes_inactive < min_need + 2:
                        # кнопка напоминания
                        kb = InlineKeyboardBuilder()
                        if btn_text == "🔁 Вернуться в меню":
                            kb.button(text=btn_text, callback_data="screen:start")
                        elif btn_text == "💳 Тарифы":
                            kb.button(text=btn_text, callback_data="screen:tariffs")
                        elif btn_text == "🛠 Поддержка":
                            kb.button(text=btn_text, callback_data="screen:support")
                        elif btn_text == "✅ Выбрать тариф":
                            kb.button(text=btn_text, callback_data="screen:tariffs")
                        else:
                            kb.button(text=btn_text, callback_data="screen:start")
                        kb.adjust(1)

                        try:
                            m = await bot.send_message(tg_id, text, reply_markup=kb.as_markup())
                            await add_reminder_message_id(tg_id, m.message_id)
                        except Exception:
                            pass

            await asyncio.sleep(30)
        except Exception as e:
            print("reminders_worker error:", e)
            await asyncio.sleep(5)


# ============================================================
# 11) AIOGRAM ХЕНДЛЕРЫ (ВАЖНО: dp уже создан ВЫШЕ!)
# ============================================================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = await ensure_user(message)
    await show_screen(message.chat.id, user, "start")


@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    user = await ensure_user(message)
    if not is_admin(user["telegram_id"]):
        await message.answer("❌ Нет доступа.")
        return

    await message.answer("🛡 <b>Админ-панель</b>", reply_markup=kb_admin_panel().as_markup())


@dp.callback_query(F.data.startswith("screen:"))
async def on_screen(callback: CallbackQuery):
    user = await ensure_user(callback)
    screen = callback.data.split(":", 1)[1]
    await callback.answer()
    await show_screen(callback.message.chat.id, user, screen)


@dp.callback_query(F.data.startswith("buy:"))
async def on_buy(callback: CallbackQuery):
    user = await ensure_user(callback)
    plan = callback.data.split(":", 1)[1]
    await callback.answer()

    url = GUMROAD_URLS.get(plan, "")
    if not url:
        await bot.send_message(callback.message.chat.id, "❌ Ссылка на оплату не настроена.")
        return

    # ВАЖНО: передаём tg id в оплату, чтобы webhook знал кому дать доступ
    # Gumroad принимает параметры query string. Пример: ?tg=123&plan=lite
    pay_link = url
    sep = "&" if "?" in pay_link else "?"
    pay_link = f"{pay_link}{sep}tg={user['telegram_id']}&plan={plan}"

    text = (
        f"💳 <b>Оплата тарифа {TARIFFS[plan]['title']}</b>\n\n"
        f"Перейдите по ссылке:\n"
        f"<a href=\"{pay_link}\">👉 Оплатить</a>\n\n"
        "После оплаты доступ включится автоматически."
    )
    await bot.send_message(callback.message.chat.id, text)


@dp.callback_query(F.data == "admin:panel")
async def admin_panel(callback: CallbackQuery):
    user = await ensure_user(callback)
    if not is_admin(user["telegram_id"]):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await bot.send_message(callback.message.chat.id, "🛡 <b>Админ-панель</b>", reply_markup=kb_admin_panel().as_markup())


@dp.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery):
    user = await ensure_user(callback)
    if not is_admin(user["telegram_id"]):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()

    pool = await db()
    async with pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT count(*) FROM users")
        paid_users = await conn.fetchval("SELECT count(*) FROM users WHERE paid_until > now()")
        trial_users = await conn.fetchval("SELECT count(*) FROM users WHERE trial_until > now() AND (paid_until IS NULL OR paid_until <= now())")
        total_money = await conn.fetchval("SELECT COALESCE(sum(total_paid_cents),0) FROM users")

    text = (
        "📊 <b>Статистика</b>\n"
        f"Пользователей: <b>{total_users}</b>\n"
        f"Платных активных: <b>{paid_users}</b>\n"
        f"На пробном: <b>{trial_users}</b>\n"
        f"Всего заработано (центов): <b>{total_money}</b>\n"
    )
    await bot.send_message(callback.message.chat.id, text, reply_markup=kb_admin_panel().as_markup())


@dp.callback_query(F.data == "admin:ask_user_id")
async def admin_ask_user_id(callback: CallbackQuery):
    user = await ensure_user(callback)
    if not is_admin(user["telegram_id"]):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()

    # Ставим состояние "жду ID"
    pool = await db()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET support_state='admin_wait_id' WHERE telegram_id=$1", user["telegram_id"])

    await bot.send_message(callback.message.chat.id, "Введите Telegram ID пользователя (число).")


@dp.message()
async def on_any_text(message: Message):
    """
    ВАЖНОЕ ПРАВИЛО:
    - Если пользователь в диалоге поддержки (in_dialog) — его сообщения идут админу
    - Если админ в диалоге — его сообщения идут пользователю
    - Иначе: "неверный ввод" + кнопка в начало
    """
    user = await ensure_user(message)

    # бан
    if user.get("is_banned"):
        await message.answer(TEXT_BANNED)
        return

    # лимиты сообщений (пример)
    await inc_daily_messages(user["telegram_id"])
    daily = await get_daily_messages(user["telegram_id"])
    plan = user.get("plan", "free")
    limit = TARIFFS.get(plan, TARIFFS["free"])["messages_per_day_limit"]
    if daily > limit:
        await message.answer("⛔ Лимит сообщений на сегодня исчерпан. Оформите тариф выше.")
        return

    # Админ режим "жду ID пользователя"
    if is_admin(user["telegram_id"]):
        if user.get("support_state") == "admin_wait_id":
            if message.text and message.text.strip().isdigit():
                target_id = int(message.text.strip())
                target = await get_user_by_id(target_id)
                pool = await db()
                async with pool.acquire() as conn:
                    await conn.execute("UPDATE users SET support_state='none' WHERE telegram_id=$1", user["telegram_id"])

                if not target:
                    await message.answer("❌ Пользователь не найден.")
                    return

                t = now_utc()
                paid_until = target.get("paid_until")
                trial_until = target.get("trial_until")
                plan2 = target.get("plan", "free")
                banned = bool(target.get("is_banned"))

                info = [f"👤 <b>Пользователь</b> <code>{target_id}</code>"]
                info.append(f"Тариф: <b>{TARIFFS.get(plan2, TARIFFS['free'])['title']}</b>")
                info.append(f"Бан: <b>{'Да' if banned else 'Нет'}</b>")

                if paid_until and paid_until > t:
                    info.append(f"✅ Оплачено до: <b>{paid_until.strftime('%Y-%m-%d %H:%M')}</b> (UTC)")
                elif trial_until and trial_until > t:
                    info.append(f"🎁 Пробный до: <b>{trial_until.strftime('%Y-%m-%d %H:%M')}</b> (UTC)")
                else:
                    info.append("❌ Доступ не активен")

                info.append(f"💰 Всего оплачено (центов): <b>{target.get('total_paid_cents', 0)}</b>")

                await message.answer("\n".join(info), reply_markup=kb_admin_user(target_id, banned).as_markup())
                return

            await message.answer("Введите числовой Telegram ID.")
            return

    # Пользователь: состояние поддержки
    support_state = user.get("support_state")

    # Если пользователь нажал "Поддержка" и мы ждём вопрос — любое сообщение считается вопросом и летит админу
    if support_state in ("waiting_user", "in_dialog"):
        # создаём/открываем thread
        pool = await db()
        async with pool.acquire() as conn:
            thread = await conn.fetchrow("SELECT * FROM support_threads WHERE telegram_id=$1", user["telegram_id"])
            if not thread:
                await conn.execute("INSERT INTO support_threads (telegram_id, is_open) VALUES ($1, TRUE)", user["telegram_id"])
                thread = await conn.fetchrow("SELECT * FROM support_threads WHERE telegram_id=$1", user["telegram_id"])
            thread_id = thread["id"]

            await conn.execute(
                "INSERT INTO support_messages (thread_id, sender, text) VALUES ($1,'user',$2)",
                thread_id, message.text or ""
            )

            # переводим в режим диалога (чтобы не было “неверный ввод”)
            await conn.execute(
                "UPDATE users SET support_state='in_dialog' WHERE telegram_id=$1",
                user["telegram_id"]
            )

        # пересылаем админу
        for admin_id in ADMIN_IDS:
            try:
                kb = InlineKeyboardBuilder()
                kb.button(text="💬 Открыть диалог", callback_data=f"admin:open_dialog:{user['telegram_id']}")
                kb.button(text="✅ Завершить диалог", callback_data=f"admin:close_dialog:{user['telegram_id']}")
                kb.adjust(1, 1)

                await bot.send_message(
                    admin_id,
                    f"💬 <b>Сообщение от пользователя</b> <code>{user['telegram_id']}</code>:\n\n"
                    f"{(message.text or '').strip()}",
                    reply_markup=kb.as_markup()
                )
            except Exception:
                pass

        await message.answer("✅ Сообщение отправлено в поддержку. Ожидайте ответа.")
        return

    # ИНАЧЕ: если просто пишет что-то — неверный ввод
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 В начало", callback_data="screen:start")
    kb.adjust(1)
    await message.answer("❗ Неверный ввод. Используйте кнопки ниже.", reply_markup=kb.as_markup())


@dp.callback_query(F.data.startswith("admin:user:"))
async def admin_user_profile(callback: CallbackQuery):
    admin = await ensure_user(callback)
    if not is_admin(admin["telegram_id"]):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()

    target_id = int(callback.data.split(":")[-1])
    target = await get_user_by_id(target_id)
    if not target:
        await bot.send_message(callback.message.chat.id, "❌ Пользователь не найден.")
        return

    t = now_utc()
    paid_until = target.get("paid_until")
    trial_until = target.get("trial_until")
    plan2 = target.get("plan", "free")
    banned = bool(target.get("is_banned"))

    info = [f"👤 <b>Пользователь</b> <code>{target_id}</code>"]
    info.append(f"Тариф: <b>{TARIFFS.get(plan2, TARIFFS['free'])['title']}</b>")
    info.append(f"Бан: <b>{'Да' if banned else 'Нет'}</b>")

    if paid_until and paid_until > t:
        info.append(f"✅ Оплачено до: <b>{paid_until.strftime('%Y-%m-%d %H:%M')}</b> (UTC)")
    elif trial_until and trial_until > t:
        info.append(f"🎁 Пробный до: <b>{trial_until.strftime('%Y-%m-%d %H:%M')}</b> (UTC)")
    else:
        info.append("❌ Доступ не активен")

    info.append(f"💰 Всего оплачено (центов): <b>{target.get('total_paid_cents', 0)}</b>")

    # количество ботов
    pool = await db()
    async with pool.acquire() as conn:
        bots_count = await conn.fetchval("SELECT count(*) FROM bots WHERE owner_telegram_id=$1", target_id)
        bots_names = await conn.fetch("SELECT bot_name FROM bots WHERE owner_telegram_id=$1 ORDER BY id DESC LIMIT 10", target_id)
    info.append(f"🤖 Ботов: <b>{bots_count}</b>")
    if bots_names:
        info.append("Последние боты: " + ", ".join([b["bot_name"] for b in bots_names]))

    # последние 10 сообщений поддержки
    pool = await db()
    async with pool.acquire() as conn:
        thread = await conn.fetchrow("SELECT * FROM support_threads WHERE telegram_id=$1", target_id)
        if thread:
            msgs = await conn.fetch(
                """
                SELECT sender, text, created_at
                FROM support_messages
                WHERE thread_id=$1
                ORDER BY id DESC
                LIMIT 10
                """,
                thread["id"]
            )
        else:
            msgs = []

    if msgs:
        info.append("\n🧾 <b>Последние сообщения поддержки</b> (до 10):")
        for m in reversed(msgs):
            who = "👤" if m["sender"] == "user" else "🛡"
            info.append(f"{who} {m['text']}")

    await bot.send_message(callback.message.chat.id, "\n".join(info), reply_markup=kb_admin_user(target_id, banned).as_markup())


@dp.callback_query(F.data.startswith("admin:ban:"))
async def admin_ban(callback: CallbackQuery):
    admin = await ensure_user(callback)
    if not is_admin(admin["telegram_id"]):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()

    target_id = int(callback.data.split(":")[-1])
    target = await get_user_by_id(target_id)
    if not target:
        await bot.send_message(callback.message.chat.id, "❌ Пользователь не найден.")
        return

    new_value = not bool(target.get("is_banned"))
    await ban_user(target_id, new_value)

    await bot.send_message(
        callback.message.chat.id,
        f"{'⛔ Забанен' if new_value else '✅ Разбанен'} пользователь <code>{target_id}</code>"
    )

    # пользователю тоже сообщим
    try:
        if new_value:
            await bot.send_message(target_id, TEXT_BANNED)
        else:
            await bot.send_message(target_id, "✅ Бан снят. Нажмите /start")
    except Exception:
        pass


@dp.callback_query(F.data.startswith("admin:open_dialog:"))
async def admin_open_dialog(callback: CallbackQuery):
    admin = await ensure_user(callback)
    if not is_admin(admin["telegram_id"]):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()

    target_id = int(callback.data.split(":")[-1])

    # Открываем thread и ставим состояние пользователю "in_dialog"
    pool = await db()
    async with pool.acquire() as conn:
        thread = await conn.fetchrow("SELECT * FROM support_threads WHERE telegram_id=$1", target_id)
        if not thread:
            await conn.execute("INSERT INTO support_threads (telegram_id, is_open) VALUES ($1, TRUE)", target_id)
            thread = await conn.fetchrow("SELECT * FROM support_threads WHERE telegram_id=$1", target_id)

        await conn.execute("UPDATE support_threads SET is_open=TRUE, closed_at=NULL WHERE telegram_id=$1", target_id)
        await conn.execute("UPDATE users SET support_state='in_dialog' WHERE telegram_id=$1", target_id)

    # Сообщение админу
    await bot.send_message(
        callback.message.chat.id,
        f"✅ <b>Диалог открыт.</b>\n\n"
        f"Теперь всё, что вы пишете — уйдёт пользователю <code>{target_id}</code>.\n"
        f"Чтобы завершить — нажмите кнопку ниже.",
        reply_markup=kb_admin_dialog(target_id).as_markup()
    )

    # Сообщение пользователю
    try:
        await bot.send_message(
            target_id,
            "✅ <b>Менеджер подключился.</b>\nНапишите сообщение — мы ответим.",
        )
    except Exception:
        pass


@dp.callback_query(F.data.startswith("admin:close_dialog:"))
async def admin_close_dialog(callback: CallbackQuery):
    admin = await ensure_user(callback)
    if not is_admin(admin["telegram_id"]):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()

    target_id = int(callback.data.split(":")[-1])

    pool = await db()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE support_threads SET is_open=FALSE, closed_at=now() WHERE telegram_id=$1", target_id)
        await conn.execute("UPDATE users SET support_state='none' WHERE telegram_id=$1", target_id)

    await bot.send_message(callback.message.chat.id, "✅ Диалог завершён.", reply_markup=kb_admin_panel().as_markup())

    try:
        kb = InlineKeyboardBuilder()
        kb.button(text="🏠 В начало", callback_data="screen:start")
        kb.adjust(1)
        await bot.send_message(target_id, "✅ Диалог завершён.", reply_markup=kb.as_markup())
    except Exception:
        pass


# ============================================================
# 12) ПЕРЕСЫЛКА СООБЩЕНИЙ ОТ АДМИНА К ПОЛЬЗОВАТЕЛЮ (КАК “ЧАТ”)
#     (Фундамент: если ты админ и открыл диалог — всё что пишешь отправляется юзеру)
# ============================================================

@dp.message(F.from_user.id.in_(ADMIN_IDS))
async def admin_text_router(message: Message):
    """
    Этот хендлер ловит сообщения админа.
    Чтобы понять КОМУ слать — мы делаем просто:
    Админ отвечает на сообщение от пользователя (reply), и мы берём user_id из текста/кнопок.
    Но это сложно. Поэтому:
    В этом фундаменте — админ общается через кнопки “Открыть диалог”,
    а дальше просто пишет — мы спрашиваем его “кому?” НЕ будем.
    """

    # Если админ пишет /admin или /start — не мешаем
    if message.text and message.text.startswith("/"):
        return

    # Упростим: если админ хочет отвечать — он должен писать в формате:
    # 123456789: текст
    # (потом можно сделать красивее, но фундамент уже рабочий)
    txt = (message.text or "").strip()
    if ":" not in txt:
        return

    left, right = txt.split(":", 1)
    left = left.strip()
    right = right.strip()

    if not left.isdigit() or not right:
        return

    target_id = int(left)

    # сохраняем в базу
    pool = await db()
    async with pool.acquire() as conn:
        thread = await conn.fetchrow("SELECT * FROM support_threads WHERE telegram_id=$1", target_id)
        if not thread:
            await conn.execute("INSERT INTO support_threads (telegram_id, is_open) VALUES ($1, TRUE)", target_id)
            thread = await conn.fetchrow("SELECT * FROM support_threads WHERE telegram_id=$1", target_id)

        await conn.execute(
            "INSERT INTO support_messages (thread_id, sender, text) VALUES ($1,'admin',$2)",
            thread["id"], right
        )

    # отправляем пользователю
    try:
        await bot.send_message(target_id, f"🛡 <b>Поддержка:</b>\n{right}")
        await message.answer("✅ Отправлено.")
    except Exception:
        await message.answer("❌ Не удалось отправить (пользователь недоступен).")


# ============================================================
# 13) WEBHOOK ОПЛАТЫ (Gumroad)
#     Главная идея: в оплату ты передаёшь tg=ID, и webhook даёт доступ этому ID.
# ============================================================

def verify_gumroad_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """
    Опционально. Если Gumroad даёт подпись — можно проверить.
    Если не хочешь — можешь не использовать.
    """
    if not secret:
        return True
    mac = hmac.new(secret.encode(), msg=raw_body, digestmod=hashlib.sha256).hexdigest()
    # иногда подпись может быть в разных заголовках — зависит от Gumroad.
    # Поэтому используем “best effort”.
    return hmac.compare_digest(mac, signature or "")

@app.post("/webhook/gumroad")
async def gumroad_webhook(request: Request):
    """
    Как дергать:
    /webhook/gumroad?secret=WEBHOOK_SECRET
    """
    secret = request.query_params.get("secret", "")
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="bad secret")

    raw = await request.body()
    # Gumroad часто шлёт form-urlencoded, но бывает json — мы обработаем оба
    content_type = request.headers.get("content-type", "")
    data: Dict[str, Any] = {}

    if "application/json" in content_type:
        data = json.loads(raw.decode("utf-8") or "{}")
    else:
        # form-urlencoded
        form = await request.form()
        data = dict(form)

    # Пытаемся вытащить tg id
    tg = data.get("tg") or data.get("telegram_id")
    if not tg:
        # иногда tg лежит в custom_fields или “variants” — это зависит от настройки
        # фундамент: требуем tg=... в ссылке оплаты — это самый надёжный способ
        raise HTTPException(status_code=400, detail="tg not provided")

    if isinstance(tg, str) and tg.isdigit():
        tg_id = int(tg)
    else:
        raise HTTPException(status_code=400, detail="bad tg format")

    plan = (data.get("plan") or "pro").strip().lower()
    if plan not in ("lite", "plus", "pro"):
        plan = "pro"

    # сумма (если есть)
    amount_cents = 0
    for key in ("price_cents", "amount_cents", "sale_price_cents"):
        v = data.get(key)
        if v and str(v).isdigit():
            amount_cents = int(v)
            break

    payment_id = str(data.get("sale_id") or data.get("payment_id") or "")

    # записываем payment
    pool = await db()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO payments (telegram_id, provider_payment_id, plan, amount_cents, currency, raw)
            VALUES ($1,$2,$3,$4,$5,$6)
            """,
            tg_id, payment_id, plan, amount_cents, str(data.get("currency") or ""), json.dumps(data)
        )

    # даём доступ на 30 дней
    await update_user_subscription(tg_id, plan, ПЛАТНЫЕ_ДНИ, amount_cents)

    # уведомим пользователя
    try:
        await bot.send_message(
            tg_id,
            f"✅ Оплата получена!\n"
            f"Тариф: <b>{TARIFFS[plan]['title']}</b>\n"
            f"Доступ активирован на <b>{ПЛАТНЫЕ_ДНИ} дней</b>."
        )
    except Exception:
        pass

    return {"ok": True}


# ============================================================
# 14) HEALTHCHECK
# ============================================================

@app.get("/")
async def root():
    return {"status": "ok", "service": "bot-builder"}

@app.get("/health")
async def health():
    return {"ok": True}


# ============================================================
# 15) STARTUP/SHUTDOWN (Railway)
#     Мы запускаем:
#     - db pool
#     - миграции
#     - reminders worker
#     - aiogram polling
# ============================================================

@app.on_event("startup")
async def on_startup():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)

    if AUTO_MIGRATE:
        async with db_pool.acquire() as conn:
            await conn.execute(MIGRATION_SQL)

    # запускаем напоминания
    asyncio.create_task(reminders_worker())

    # запускаем бота (polling)
    asyncio.create_task(dp.start_polling(bot))

    print("✅ Startup complete: db + polling + reminders")

@app.on_event("shutdown")
async def on_shutdown():
    global db_pool
    if db_pool:
        await db_pool.close()
        db_pool = None
    print("🛑 Shutdown complete")


