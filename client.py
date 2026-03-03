# client.py
# =========================================================
# ЗАЧЕМ ЭТО:
# - это КЛИЕНТСКИЙ интерфейс:
#   /start, кнопки, "Мои боты", "Добавить бота"
# - тут нет админки, нет оплат, нет тарифов — только клиент
# - КАЖДАЯ кнопка может выбирать: удалять экран или нет
#   (wipe=1 или wipe=0 в callback_data)
# =========================================================

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import ContextTypes

import db as DB
import ui as UI


# ---------- ТЕКСТЫ (поменяешь потом под себя) ----------
TXT_START = (
    "👋 <b>Конструктор ботов</b>\n\n"
    "Тут будет сборка бота по кнопкам.\n"
    "Сейчас мы ставим фундамент: экраны + исчезновение сообщений + мои боты.\n\n"
    "Выбирайте действие:"
)

TXT_MY_BOTS_EMPTY = (
    "🤖 <b>Мои боты</b>\n\n"
    "Пока нет созданных ботов.\n"
    "Нажмите «➕ Добавить бота»."
)

TXT_ADD_BOT = (
    "➕ <b>Добавить бота</b>\n\n"
    "Отправьте ОДНИМ сообщением так:\n"
    "<code>Название | @username_bot</code>\n\n"
    "Пример:\n"
    "<code>Магазин одежды | @my_shop_bot</code>\n\n"
    "⚠️ Сейчас это просто сохранение в базу.\n"
    "Позже заменим на настоящий конструктор."
)


# ---------- КНОПКИ / ЭКРАНЫ ----------
def kb_start():
    # wipe=1 -> этот переход будет удалять прошлые экраны
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Мои боты", callback_data="c:my_bots:wipe=1")],
        [InlineKeyboardButton("➕ Добавить бота", callback_data="c:add_bot:wipe=1")],
        [InlineKeyboardButton("ℹ️ Настройка удаления экранов", callback_data="c:help_wipe:wipe=1")],
    ])

def kb_back_to_start():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ В начало", callback_data="c:start:wipe=1")]
    ])

def kb_my_bots(owner_id: int):
    bots = DB.list_user_bots(owner_id)

    rows = []
    if not bots:
        rows.append([InlineKeyboardButton("➕ Добавить бота", callback_data="c:add_bot:wipe=1")])
        rows.append([InlineKeyboardButton("⬅️ В начало", callback_data="c:start:wipe=1")])
        return InlineKeyboardMarkup(rows)

    # Каждая строка — бот. Кнопка "Открыть" — это ссылка на t.me/username
    for b in bots[:50]:
        title = b["title"]
        uname = b["bot_username"].lstrip("@")
        rows.append([
            InlineKeyboardButton(f"🤖 {title}", callback_data=f"c:bot:{b['id']}:wipe=1"),
            InlineKeyboardButton("↗️ Открыть", url=f"https://t.me/{uname}"),
        ])

    rows.append([InlineKeyboardButton("⬅️ В начало", callback_data="c:start:wipe=1")])
    return InlineKeyboardMarkup(rows)

def kb_bot_card(bot_id: int):
    return InlineKeyboardMarkup([
        # wipe=0 пример: если хочешь НЕ удалять экран при нажатии
        [InlineKeyboardButton("⬅️ К списку", callback_data="c:my_bots:wipe=1")],
        [InlineKeyboardButton("⬅️ В начало", callback_data="c:start:wipe=1")],
    ])

def kb_help_wipe():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Понял", callback_data="c:start:wipe=1")]
    ])


# ---------- ВНУТРЕННЕЕ состояние: ждём ввод "Название | @бот" ----------
# (минимально, без FSM — просто флажок в памяти процесса)
WAITING_ADD_BOT = set()


# ---------- РЕНДЕР ЭКРАНА ----------
async def show_start(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, wipe: bool):
    await UI.send_screen(context, user_id, chat_id, TXT_START, kb_start(), wipe=wipe, track=True)

async def show_my_bots(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, wipe: bool):
    bots = DB.list_user_bots(user_id)
    if not bots:
        text = TXT_MY_BOTS_EMPTY
    else:
        text = "🤖 <b>Мои боты</b>\n\nВыберите бота или нажмите «Открыть»."

    await UI.send_screen(context, user_id, chat_id, text, kb_my_bots(user_id), wipe=wipe, track=True)

async def show_add_bot(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, wipe: bool):
    WAITING_ADD_BOT.add(user_id)
    await UI.send_screen(context, user_id, chat_id, TXT_ADD_BOT, kb_back_to_start(), wipe=wipe, track=True)

async def show_help_wipe(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, wipe: bool):
    text = (
        "ℹ️ <b>Как работает удаление экранов</b>\n\n"
        "Каждая кнопка у нас содержит параметр <code>wipe</code>:\n"
        "• <code>wipe=1</code> — перед показом нового экрана бот удалит старые сообщения.\n"
        "• <code>wipe=0</code> — старые сообщения НЕ удаляем.\n\n"
        "Это нужно для конструктора: клиент сам решит, какие переходы “чистят экран”."
    )
    await UI.send_screen(context, user_id, chat_id, text, kb_help_wipe(), wipe=wipe, track=True)

async def show_bot_card(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, bot_id: int, wipe: bool):
    b = DB.get_user_bot(user_id, bot_id)
    if not b:
        await UI.send_screen(context, user_id, chat_id, "❌ Бот не найден.", kb_back_to_start(), wipe=wipe, track=True)
        return

    uname = b["bot_username"].lstrip("@")
    text = (
        f"🤖 <b>{b['title']}</b>\n\n"
        f"Username: <code>@{uname}</code>\n\n"
        "Позже тут будет: сценарии, кнопки, экраны, оплаты."
    )
    await UI.send_screen(context, user_id, chat_id, text, kb_bot_card(bot_id), wipe=wipe, track=True)


# ---------- HANDLERS ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    DB.upsert_user(u.id, u.first_name or "", u.username or "")
    WAITING_ADD_BOT.discard(u.id)

    await show_start(context, u.id, update.effective_chat.id, wipe=True)

def _parse_wipe(data: str) -> bool:
    # data типа "c:start:wipe=1"
    return "wipe=1" in data

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return

    await q.answer()
    # ВАЖНО: удаляем сообщение, где нажали кнопку (тоже эффект исчезновения)
    await UI.delete_clicked_message(update, context)

    u = update.effective_user
    DB.upsert_user(u.id, u.first_name or "", u.username or "")

    data = q.data or ""
    wipe = _parse_wipe(data)

    # роутер клиентских callback
    # Форматы:
    # c:start:wipe=1
    # c:my_bots:wipe=1
    # c:add_bot:wipe=1
    # c:help_wipe:wipe=1
    # c:bot:<id>:wipe=1
    if data.startswith("c:start"):
        WAITING_ADD_BOT.discard(u.id)
        await show_start(context, u.id, q.message.chat_id, wipe=wipe)
        return

    if data.startswith("c:my_bots"):
        WAITING_ADD_BOT.discard(u.id)
        await show_my_bots(context, u.id, q.message.chat_id, wipe=wipe)
        return

    if data.startswith("c:add_bot"):
        await show_add_bot(context, u.id, q.message.chat_id, wipe=wipe)
        return

    if data.startswith("c:help_wipe"):
        WAITING_ADD_BOT.discard(u.id)
        await show_help_wipe(context, u.id, q.message.chat_id, wipe=wipe)
        return

    if data.startswith("c:bot:"):
        WAITING_ADD_BOT.discard(u.id)
        try:
            parts = data.split(":")
            bot_id = int(parts[2])
        except Exception:
            await UI.send_screen(context, u.id, q.message.chat_id, "❌ Ошибка bot_id.", kb_back_to_start(), wipe=wipe, track=True)
            return
        await show_bot_card(context, u.id, q.message.chat_id, bot_id, wipe=wipe)
        return

    # неизвестная кнопка
    WAITING_ADD_BOT.discard(u.id)
    await UI.send_screen(context, u.id, q.message.chat_id, "❌ Неизвестная команда.", kb_back_to_start(), wipe=True, track=True)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    DB.upsert_user(u.id, u.first_name or "", u.username or "")

    text = (update.message.text or "").strip()
    if not text:
        return

    # если ждём добавление бота
    if u.id in WAITING_ADD_BOT:
        # формат: "Название | @bot"
        if "|" not in text:
            await UI.send_screen(
                context, u.id, update.effective_chat.id,
                "❌ Неверный формат.\nНужно так:\n<code>Название | @username_bot</code>",
                kb_back_to_start(),
                wipe=False,  # не трогаем экран, просто подсказка
                track=True,
            )
            return

        title, uname = [x.strip() for x in text.split("|", 1)]
        if not title or not uname:
            await UI.send_screen(
                context, u.id, update.effective_chat.id,
                "❌ Пустое название или username.",
                kb_back_to_start(),
                wipe=False,
                track=True,
            )
            return

        bot_id = DB.add_user_bot(u.id, title, uname)
        WAITING_ADD_BOT.discard(u.id)

        # делаем красиво: после добавления — показываем карточку бота и чистим экран
        await show_bot_card(context, u.id, update.effective_chat.id, bot_id, wipe=True)
        return

    # если не ждём ввод — для клиента пока просто возвращаем в начало (потом будет конструктор)
    await show_start(context, u.id, update.effective_chat.id, wipe=True)

