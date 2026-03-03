# client.py
# =========================================================
# Зачем этот файл:
# - здесь клиентский интерфейс (что видит пользователь)
# - экраны, тексты, кнопки, переходы
# - всё без админки/оплат пока (добавим позже отдельными файлами)
# =========================================================

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import ContextTypes
import db
import ui

# ---------- Тексты ----------

START_TEXT = (
    "🤖 <b>Конструктор ботов</b>\n\n"
    "Выберите действие:"
)

MY_BOTS_TEXT = (
    "🧩 <b>Мои боты</b>\n\n"
    "Ниже список ваших ботов.\n"
)

ADD_BOT_TEXT = (
    "➕ <b>Добавить бота</b>\n\n"
    "Отправьте одним сообщением:\n"
    "<code>Название | ссылка</code>\n\n"
    "Пример:\n"
    "<code>Мой магазин | https://t.me/myshop_bot</code>"
)

INVALID_TEXT = (
    "❌ Неверный ввод.\n\n"
    "Нажмите «🏁 В начало»."
)

# ---------- Напоминания (пока 2 штуки, потом расширим) ----------
REM_START = [(60, "⏳ Вы ещё тут? Выберите кнопку ниже."), (180, "🔔 Напоминание: выберите действие.")]
REM_MYBOTS = [(60, "⏳ Хотите открыть или добавить бота?")]

# ---------- Кнопки ----------

def kb_start():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧩 Мои боты", callback_data="go:my_bots")],
        [InlineKeyboardButton("➕ Добавить бота", callback_data="go:add_bot")],
    ])

def kb_to_start():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏁 В начало", callback_data="go:start")]
    ])

def kb_my_bots(rows):
    # rows = list of (title, link)
    buttons = []
    for title, link in rows:
        buttons.append([InlineKeyboardButton(f"🔗 {title}", url=link)])
    buttons.append([InlineKeyboardButton("➕ Добавить бота", callback_data="go:add_bot")])
    buttons.append([InlineKeyboardButton("🏁 В начало", callback_data="go:start")])
    return InlineKeyboardMarkup(buttons)

# ---------- Роутинг экранов ----------

async def go_screen(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, screen: str):
    chat_id = update.effective_chat.id

    # сохраняем экран
    db.set_user_field(user_id, "last_screen", screen)

    # отменяем старые напоминания
    ui.cancel_reminders(context, user_id)

    # показываем экран + ставим напоминания
    if screen == "start":
        await ui.send_screen(context, chat_id, user_id, START_TEXT, kb_start())
        ui.schedule_reminders(context, user_id, chat_id, REM_START, kb_start())
        return

    if screen == "my_bots":
        bots = db.list_my_bots(user_id)
        rows = [(b["title"], b["bot_link"]) for b in bots] if bots else []
        text = MY_BOTS_TEXT
        if not rows:
            text += "\n— пока пусто. Нажмите «Добавить бота»."
        await ui.send_screen(context, chat_id, user_id, text, kb_my_bots(rows))
        ui.schedule_reminders(context, user_id, chat_id, REM_MYBOTS, kb_my_bots(rows))
        return

    if screen == "add_bot":
        await ui.send_screen(context, chat_id, user_id, ADD_BOT_TEXT, kb_to_start())
        return

    await ui.send_screen(context, chat_id, user_id, INVALID_TEXT, kb_to_start())

# ---------- handlers ----------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.first_name or "", u.username or "")
    row = db.get_user(u.id)
    if row and row["banned"]:
        return

    await go_screen(update, context, u.id, "start")


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    # удаляем сообщение, на котором нажали (в том числе напоминания)
    await ui.delete_clicked_message(q)

    u = update.effective_user
    db.upsert_user(u.id, u.first_name or "", u.username or "")
    row = db.get_user(u.id)
    if row and row["banned"]:
        return

    data = q.data
    if data.startswith("go:"):
        screen = data.split(":", 1)[1]
        await go_screen(update, context, u.id, screen)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.first_name or "", u.username or "")
    row = db.get_user(u.id)
    if row and row["banned"]:
        return

    text = (update.message.text or "").strip()
    if not text:
        return

    # если пользователь на экране add_bot — принимаем формат "Название | ссылка"
    if row and row["last_screen"] == "add_bot":
        if "|" not in text:
            await ui.send_screen(context, update.effective_chat.id, u.id, INVALID_TEXT, kb_to_start())
            return

        title, link = [x.strip() for x in text.split("|", 1)]
        if not title or not link:
            await ui.send_screen(context, update.effective_chat.id, u.id, INVALID_TEXT, kb_to_start())
            return

        db.add_my_bot(u.id, title, link)
        # после добавления — сразу в "Мои боты"
        await go_screen(update, context, u.id, "my_bots")
        return

    # иначе — неверный ввод
    await ui.send_screen(context, update.effective_chat.id, u.id, INVALID_TEXT, kb_to_start())
