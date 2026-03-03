# ui.py
# =========================================================
# ЗАЧЕМ ЭТО:
# - тут вся "магия исчезновения":
#   1) бот помнит msg_id своих сообщений (db.bot_msgs)
#   2) перед показом нового экрана удаляет старые
# - тут единая функция send_screen(), чтобы клиент/админ
#   показывали "экраны" одинаково
# - тут удаление "нажатого" сообщения (кнопка → сообщение исчезло)
# =========================================================

from telegram import InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

import db as DB


async def delete_message_safe(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_id: int):
    """
    ЗАЧЕМ:
    - Telegram иногда не даёт удалить (уже удалено / плохой id)
    - чтобы бот не падал с ошибкой
    """
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except BadRequest:
        # уже удалено / нельзя удалить — молча игнорим
        pass
    except Exception:
        pass


async def wipe_bot_messages(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int):
    """
    ЗАЧЕМ:
    - "эффект исчезновения" экрана:
      удаляем ВСЕ прошлые сообщения, которые бот слал пользователю
    """
    msg_ids = DB.get_bot_msgs(user_id, chat_id)
    for mid in msg_ids:
        await delete_message_safe(context, chat_id, mid)
    DB.clear_bot_msgs(user_id, chat_id)


async def send_screen(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int,
    text: str,
    keyboard: InlineKeyboardMarkup,
    *,
    wipe: bool,
    track: bool,
    disable_preview: bool = True,
):
    """
    ЗАЧЕМ:
    - единый способ показывать "экран"
    - wipe=True  -> перед показом удаляем старое (исчезновение)
    - track=True -> запоминаем msg_id, чтобы удалить позже
    """
    if wipe:
        await wipe_bot_messages(context, user_id, chat_id)

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=disable_preview,
    )

    if track:
        DB.add_bot_msg(user_id, chat_id, msg.message_id)

    return msg


async def delete_clicked_message(update, context: ContextTypes.DEFAULT_TYPE):
    """
    ЗАЧЕМ:
    - когда нажали кнопку, мы хотим, чтобы СТАРОЕ сообщение исчезло
    - это отдельный эффект: исчезает именно сообщение с кнопкой
    """
    q = update.callback_query
    if not q or not q.message:
        return
    await delete_message_safe(context, q.message.chat_id, q.message.message_id)

