"""
ui.py
ЗАЧЕМ:
- Единое место, где мы делаем "экраны" builder-бота.
- Тут же делаем твой эффект: при переходах можно УДАЛЯТЬ прошлое сообщение.

Как работает "удаляемый экран" в builder-боте:
- Мы храним last_message_id в platform_state.
- Перед показом нового экрана удаляем старое сообщение (если оно есть).
"""

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Message
from telegram.ext import ContextTypes
import db

async def delete_last_screen_message(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = await db.get_platform_state(user_id)
    last_id = state.get("last_message_id")
    if last_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=int(last_id))
        except Exception:
            pass

async def send_screen(
    *,
    chat_id: int,
    user_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    keyboard: InlineKeyboardMarkup,
    delete_prev: bool = True,
) -> Message:
    """
    delete_prev=True → удаляем предыдущее сообщение builder-бота (эффект "исчезновения")
    """
    if delete_prev:
        await delete_last_screen_message(chat_id, user_id, context)

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
        disable_web_page_preview=True,
        parse_mode="HTML"
    )

    await db.set_platform_state(user_id, last_message_id=msg.message_id)
    return msg

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Мои боты", callback_data="nav:my_bots")],
        [InlineKeyboardButton("➕ Подключить бота", callback_data="nav:connect_bot")],
    ])

def kb_back_and_home(back_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅ Назад", callback_data=back_cb),
            InlineKeyboardButton("🏠 Главное меню", callback_data="nav:main"),
        ]
    ])

def kb_bots_list(bots: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for b in bots:
        uname = b.get("bot_username") or "без username"
        status = "✅ Опубликован" if b.get("published") else "📝 Черновик"
        rows.append([InlineKeyboardButton(f"🤖 @{uname} • {status}", callback_data=f"bot:open:{b['id']}")])
    rows.append([InlineKeyboardButton("➕ Подключить бота", callback_data="nav:connect_bot")])
    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="nav:main")])
    return InlineKeyboardMarkup(rows)

def kb_open_bot(bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧩 Конструктор (блоки)", callback_data=f"flow:open:{bot_id}")],
        [InlineKeyboardButton("🚀 Опубликовать", callback_data=f"bot:publish:{bot_id}")],
        [InlineKeyboardButton("⬅ Назад", callback_data="nav:my_bots")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="nav:main")],
    ])

def kb_flow_home(bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Новый блок", callback_data=f"flow:new_block:{bot_id}")],
        [InlineKeyboardButton("📋 Список блоков", callback_data=f"flow:list_blocks:{bot_id}")],
        [InlineKeyboardButton("⬅ Назад", callback_data=f"bot:open:{bot_id}")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="nav:main")],
    ])

def kb_blocks_list(bot_id: int, blocks: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for bl in blocks:
        flag = "🟢 " if bl.get("is_start") else "🧱 "
        delp = "🧽" if bl.get("delete_prev") else "📌"
        rows.append([InlineKeyboardButton(f"{flag}{bl['title']} {delp}", callback_data=f"block:open:{bot_id}:{bl['id']}")])
    rows.append([InlineKeyboardButton("➕ Новый блок", callback_data=f"flow:new_block:{bot_id}")])
    rows.append([InlineKeyboardButton("⬅ Назад", callback_data=f"flow:open:{bot_id}")])
    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="nav:main")])
    return InlineKeyboardMarkup(rows)

def kb_block_editor(bot_id: int, block_id: int, delete_prev: bool) -> InlineKeyboardMarkup:
    del_title = "🧽 Удалять предыдущее: ДА" if delete_prev else "📌 Удалять предыдущее: НЕТ"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Изменить текст", callback_data=f"block:edit_text:{bot_id}:{block_id}")],
        [InlineKeyboardButton("➕ Добавить кнопку", callback_data=f"btn:add:{bot_id}:{block_id}")],
        [InlineKeyboardButton(del_title, callback_data=f"block:toggle_del:{bot_id}:{block_id}")],
        [InlineKeyboardButton("⬅ Назад", callback_data=f"flow:list_blocks:{bot_id}")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="nav:main")],
    ])

def kb_button_action_choose(bot_id: int, block_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Переход на блок", callback_data=f"btn:act:go_block:{bot_id}:{block_id}")],
        [InlineKeyboardButton("🔗 Открыть ссылку", callback_data=f"btn:act:open_url:{bot_id}:{block_id}")],
        [InlineKeyboardButton("✉️ Отправить текст", callback_data=f"btn:act:send_text:{bot_id}:{block_id}")],
        [InlineKeyboardButton("⬅ Назад", callback_data=f"block:open:{bot_id}:{block_id}")],
    ])
