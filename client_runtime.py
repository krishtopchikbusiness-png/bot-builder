"""
client_runtime.py
ЗАЧЕМ:
- Это "движок" клиентских ботов.
- Когда ты нажимаешь Publish — мы ставим webhook клиентскому боту на /tg/client/<secret>/<bot_id>
- Telegram начинает присылать апдейты по этому URL.
- Мы читаем блоки/кнопки из базы и отвечаем.

ВАЖНО:
- Здесь реализован минимальный runtime:
  /start → стартовый блок
  кнопки → переходы, ссылки, отправка текста
  delete_prev у блока → удаляет прошлое сообщение end-user'у
"""

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram import Bot as TgBot
import db

def _kb_for_block(buttons: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for b in buttons:
        if b["action_type"] == "open_url":
            rows.append([InlineKeyboardButton(b["title"], url=b["action_value"])])
        elif b["action_type"] == "go_block":
            # callback_data: go:<target_block_id>
            rows.append([InlineKeyboardButton(b["title"], callback_data=f"go:{b['action_value']}")])
        elif b["action_type"] == "send_text":
            rows.append([InlineKeyboardButton(b["title"], callback_data=f"txt:{b['id']}")])
    return InlineKeyboardMarkup(rows) if rows else InlineKeyboardMarkup([])

async def _send_block(bot: TgBot, bot_id: int, chat_id: int, tg_user_id: int, block_id: int) -> None:
    block = await db.get_block(block_id)
    if not block:
        return

    buttons = await db.list_buttons(block_id)
    kb = _kb_for_block(buttons)

    endu = await db.get_end_user(bot_id, tg_user_id)
    last_msg = endu.get("last_message_id") if endu else None

    # если блок "удаляемый" — удаляем прошлое сообщение
    if block["delete_prev"] and last_msg:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=int(last_msg))
        except Exception:
            pass

    msg = await bot.send_message(
        chat_id=chat_id,
        text=block["text"] or "",
        reply_markup=kb,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await db.upsert_end_user(bot_id, tg_user_id, block_id, msg.message_id)

async def handle_client_update(bot_id: int, update_json: dict) -> None:
    """
    Вызывается FastAPI endpoint'ом.
    """
    bot_row = await db.get_client_bot(bot_id)
    if not bot_row or not bot_row.get("published"):
        return

    bot = TgBot(token=bot_row["bot_token"])
    update = Update.de_json(update_json, bot)

    if update.message:
        chat_id = update.message.chat_id
        tg_user_id = update.message.from_user.id

        # /start или любое сообщение → стартовый блок
        start_block = await db.get_start_block(bot_id)
        if not start_block:
            return
        await _send_block(bot, bot_id, chat_id, tg_user_id, start_block["id"])
        return

    if update.callback_query:
        cq = update.callback_query
        chat_id = cq.message.chat_id
        tg_user_id = cq.from_user.id
        data = cq.data or ""

        try:
            await cq.answer()
        except Exception:
            pass

        if data.startswith("go:"):
            target = int(data.split(":")[1])
            await _send_block(bot, bot_id, chat_id, tg_user_id, target)
            return

        if data.startswith("txt:"):
            btn_id = int(data.split(":")[1])
            # найдём кнопку и отправим её action_value как текст
            # (простая реализация: берём через list_buttons блока текущего юзера)
            endu = await db.get_end_user(bot_id, tg_user_id)
            if not endu or not endu.get("current_block_id"):
                return
            buttons = await db.list_buttons(int(endu["current_block_id"]))
            for b in buttons:
                if b["id"] == btn_id and b["action_type"] == "send_text":
                    await bot.send_message(chat_id=chat_id, text=b["action_value"])
                    return
