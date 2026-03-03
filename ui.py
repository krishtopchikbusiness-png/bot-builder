# ui.py
# =========================================================
# Зачем этот файл:
# - вся "магия UI": удаление прошлых сообщений
# - удаление сообщения по нажатию кнопки
# - планирование/отмена напоминаний
# =========================================================

from telegram import InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import db


# ---------- Удаление сообщений (эффект исчезновения) ----------

async def wipe_bot_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    ids = db.list_bot_msgs(user_id)
    for mid in ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass
    db.clear_bot_msgs(user_id)


async def send_screen(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int,
                      text: str, kb: InlineKeyboardMarkup | None):
    # 1) удаляем все старые сообщения бота
    await wipe_bot_messages(context, chat_id, user_id)

    # 2) отправляем новый "экран"
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

    # 3) сохраняем msg_id, чтобы потом удалить
    db.add_bot_msg(user_id, msg.message_id)


async def delete_clicked_message(query):
    # удаляем сообщение, на котором была нажата кнопка (включая напоминания)
    try:
        await query.message.delete()
    except Exception:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass


# ---------- Напоминания (JobQueue) ----------

def cancel_reminders(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    jq = getattr(context, "job_queue", None)
    if not jq:
        return
    for job in list(jq.jobs()):
        if job.name and job.name.startswith(f"rem_{user_id}_"):
            job.schedule_removal()


async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    user_id = data["user_id"]
    chat_id = data["chat_id"]
    text = data["text"]
    kb = data["kb"]

    # Напоминание тоже добавляем в bot_msgs, чтобы потом удалялось.
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )
    db.add_bot_msg(user_id, msg.message_id)


def schedule_reminders(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int,
                       reminders: list[tuple[int, str]], kb: InlineKeyboardMarkup):
    cancel_reminders(context, user_id)
    jq = getattr(context, "job_queue", None)
    if not jq:
        return

    for i, (sec, txt) in enumerate(reminders, start=1):
        jq.run_once(
            reminder_job,
            when=sec,
            name=f"rem_{user_id}_{i}",
            data={"user_id": user_id, "chat_id": chat_id, "text": txt, "kb": kb},
        )
