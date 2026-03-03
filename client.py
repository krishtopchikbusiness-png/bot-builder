"""
===========================================================
ФАЙЛ: client.py
===========================================================

ЗАЧЕМ ЭТОТ ФАЙЛ?

Это "клиентская часть" бота:
то есть всё, что видит обычный пользователь.

Тут:
- экраны
- тексты
- кнопки
- логика переходов

Тут НЕТ:
- админ панели
- оплат
- тарифов
- поддержки

Мы специально разделяем, чтобы потом легко добавлять:
admin.py, billing.py, support.py и т.д.
===========================================================
"""

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import db
import ui


# =========================================================
# 1) ТЕКСТЫ ЭКРАНОВ
# =========================================================

"""
ВАЖНО:
parse_mode=HTML в ui.send_screen включен.
Значит ты можешь вставлять ссылки так:

<a href="https://google.com">текст ссылки</a>

и будет кликабельно.
"""

TEXT_HOME = (
    "🧩 <b>Конструктор ботов</b>\n\n"
    "Выберите действие:"
)

TEXT_MY_BOTS_EMPTY = (
    "🤖 <b>Мои боты</b>\n\n"
    "Пока пусто.\n"
    "Нажмите «➕ Добавить бота»."
)

TEXT_ADD_BOT = (
    "➕ <b>Добавить бота</b>\n\n"
    "Отправьте одним сообщением:\n"
    "<code>Название | @username_бота</code>\n\n"
    "Пример:\n"
    "<code>Магазин | @my_shop_bot</code>\n\n"
    "⚠️ Важно: пока это просто сохранение в список.\n"
    "Автосоздание ботов добавим позже."
)

TEXT_INVALID = (
    "❌ Неверный ввод.\n\n"
    "Нажмите «🏁 В начало»."
)


# =========================================================
# 2) КЛАВИАТУРЫ (кнопки)
# =========================================================

def kb_home():
    """
    Главная клавиатура.
    callback_data начинаем с c: чтобы отличать клиентские кнопки.
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Мои боты", callback_data="c:my_bots")],
        [InlineKeyboardButton("➕ Добавить бота", callback_data="c:add_bot")],
        [InlineKeyboardButton("👤 Профиль", callback_data="c:profile")],
    ])


def kb_back_home():
    """Кнопка возвращения в начало."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏁 В начало", callback_data="c:home")]
    ])


def kb_my_bots(bots: list[dict]):
    """
    Кнопки для списка ботов.
    Если у бота есть username → делаем url-кнопку на открытие бота.
    """
    rows = []

    # Список ботов
    for b in bots[:20]:
        name = b.get("bot_name", "Bot")
        username = (b.get("bot_username") or "").strip()
        if username.startswith("@"):
            url = f"https://t.me/{username[1:]}"
            rows.append([InlineKeyboardButton(f"🔗 {name}", url=url)])
        else:
            rows.append([InlineKeyboardButton(f"• {name}", callback_data="c:noop")])

    # Кнопки управления
    rows.append([InlineKeyboardButton("➕ Добавить бота", callback_data="c:add_bot")])
    rows.append([InlineKeyboardButton("🏁 В начало", callback_data="c:home")])
    return InlineKeyboardMarkup(rows)


def kb_noop():
    """Пустая кнопка-заглушка (чтобы не падало)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏁 В начало", callback_data="c:home")]
    ])


# =========================================================
# 3) ЭКРАНЫ (функции, которые показывают текст+кнопки)
# =========================================================

async def show_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Главный экран.
    Здесь мы используем ui.send_screen, чтобы:
    - удалить прошлые сообщения
    - отправить новый экран
    - сохранить message_id в БД (для удаления дальше)
    """
    u = update.effective_user
    db.save_user(u.id, u.first_name or "", u.username or "")

    await ui.send_screen(
        update=update,
        context=context,
        user_id=u.id,
        text=TEXT_HOME,
        keyboard=kb_home(),
        wipe_before=True,       # удалять старые экраны
        delete_clicked=True,    # удалять сообщение, по которому нажали
        parse_mode=ParseMode.HTML,
        disable_preview=True,
    )


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экран профиля."""
    u = update.effective_user
    row = db.get_user(u.id) or {}

    first_name = row.get("first_name", "")
    username = row.get("username", "")
    created_at = row.get("created_at", 0)

    text = (
        "👤 <b>Профиль</b>\n\n"
        f"ID: <code>{u.id}</code>\n"
        f"Имя: <b>{first_name}</b>\n"
        f"Username: <b>@{username}</b>\n" if username else
        "Username: —\n"
    )

    await ui.send_screen(
        update=update,
        context=context,
        user_id=u.id,
        text=text,
        keyboard=kb_back_home(),
        wipe_before=True,
        delete_clicked=True,
    )


async def show_my_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экран списка ботов пользователя."""
    u = update.effective_user
    bots = db.get_user_bots(u.id)

    if not bots:
        await ui.send_screen(
            update=update,
            context=context,
            user_id=u.id,
            text=TEXT_MY_BOTS_EMPTY,
            keyboard=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Добавить бота", callback_data="c:add_bot")],
                [InlineKeyboardButton("🏁 В начало", callback_data="c:home")],
            ]),
            wipe_before=True,
            delete_clicked=True,
        )
        return

    text = "🤖 <b>Мои боты</b>\n\nНажмите на бота, чтобы открыть:"
    await ui.send_screen(
        update=update,
        context=context,
        user_id=u.id,
        text=text,
        keyboard=kb_my_bots(bots),
        wipe_before=True,
        delete_clicked=True,
    )


async def show_add_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Экран добавления бота.
    После него пользователь должен отправить 1 сообщение:
    "Название | @username"
    """
    u = update.effective_user

    # Запоминаем в базе что пользователь сейчас на экране add_bot
    # (чтобы on_text понял, как обрабатывать ввод)
    # Для этого используем поле last_screen? — его нет в этой db.py.
    # Поэтому делаем проще: храним состояние в памяти (context.user_data).
    context.user_data["screen"] = "add_bot"

    await ui.send_screen(
        update=update,
        context=context,
        user_id=u.id,
        text=TEXT_ADD_BOT,
        keyboard=kb_back_home(),
        wipe_before=True,
        delete_clicked=True,
    )


async def show_invalid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экран 'Неверный ввод'."""
    u = update.effective_user
    await ui.send_screen(
        update=update,
        context=context,
        user_id=u.id,
        text=TEXT_INVALID,
        keyboard=kb_back_home(),
        wipe_before=True,
        delete_clicked=True,
    )


# =========================================================
# 4) HANDLERS (то что цепляется в main.py)
# =========================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start
    Начинаем с главного экрана.
    """
    await show_home(update, context)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик всех нажатий на кнопки.
    """
    q = update.callback_query
    await q.answer()

    data = q.data or ""

    # Заглушка
    if data == "c:noop":
        await show_home(update, context)
        return

    # Роутинг экранов
    if data == "c:home":
        await show_home(update, context)
        return

    if data == "c:profile":
        await show_profile(update, context)
        return

    if data == "c:my_bots":
        await show_my_bots(update, context)
        return

    if data == "c:add_bot":
        await show_add_bot(update, context)
        return

    # если пришло что-то неизвестное
    await show_invalid(update, context)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик обычных сообщений (не команд).

    Тут мы обрабатываем ввод, когда пользователь на экране add_bot.
    """
    u = update.effective_user
    db.save_user(u.id, u.first_name or "", u.username or "")

    text = (update.message.text or "").strip()
    if not text:
        return

    # Если пользователь на экране "add_bot", то ожидаем формат:
    # Название | @username
    if context.user_data.get("screen") == "add_bot":
        context.user_data["screen"] = ""  # сбрасываем состояние

        if "|" not in text:
            await show_invalid(update, context)
            return

        name, username = [x.strip() for x in text.split("|", 1)]
        if not name or not username:
            await show_invalid(update, context)
            return

        # username должен быть типа @botname
        if not username.startswith("@"):
            await show_invalid(update, context)
            return

        db.add_user_bot(u.id, bot_name=name, bot_username=username)

        # После добавления — сразу показываем список ботов
        await show_my_bots(update, context)
        return

    # Если не в режиме ввода — это неверный ввод
    await show_invalid(update, context)
