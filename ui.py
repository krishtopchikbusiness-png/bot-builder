"""
===========================================================
ФАЙЛ: ui.py
===========================================================

ЗАЧЕМ ЭТОТ ФАЙЛ?

Этот файл отвечает за "UI" (интерфейс) в Telegram:

✅ "ЭФФЕКТ ИСЧЕЗНОВЕНИЯ"
- когда юзер нажал кнопку → старые сообщения бота удаляются

✅ УДАЛЕНИЕ НАПОМИНАНИЙ
- если юзер нажал кнопку на напоминании → само напоминание тоже удалится

✅ ОТПРАВКА "ЭКРАНОВ"
- экран = текст + кнопки
- мы отправляем экран и сохраняем message_id в базу,
  чтобы потом удалить

ВАЖНО:
В этом файле НЕТ бизнес-логики.
Тут нет тарифов, оплат, админки.
Тут только удаление/отправка сообщений.
===========================================================
"""

from typing import Optional
from telegram import Update, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import db


# =========================================================
# 1) УДАЛЕНИЕ ОДНОГО СООБЩЕНИЯ (по message_id)
# =========================================================

async def safe_delete_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    """
    ЗАЧЕМ ЭТА ФУНКЦИЯ?

    В Telegram нельзя всегда удалить сообщение:
    - оно может быть слишком старым (редко)
    - у бота может не быть прав (в группе)
    - сообщение уже удалили

    Поэтому делаем "safe delete":
    пробуем удалить → если не получилось, молчим.
    """
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        # Не спамим ошибками, просто игнорим
        pass


# =========================================================
# 2) УДАЛЕНИЕ СООБЩЕНИЯ, ПО КОТОРОМУ НАЖАЛИ (callback)
# =========================================================

async def delete_clicked_message(update: Update):
    """
    ЗАЧЕМ ЭТА ФУНКЦИЯ?

    Когда юзер нажимает кнопку, Telegram оставляет сообщение в чате.
    Ты хотел: "нажал кнопку — сообщение исчезло".

    Это значит:
    - если это был экран → он удаляется
    - если это было напоминание → оно тоже удаляется

    Мы удаляем update.callback_query.message
    """
    q = update.callback_query
    if not q or not q.message:
        return

    try:
        await q.message.delete()
    except Exception:
        # Если удалить нельзя — хотя бы убираем кнопки, чтобы не нажимали 100 раз
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass


# =========================================================
# 3) УДАЛЕНИЕ ВСЕХ СООБЩЕНИЙ БОТА ДЛЯ ЮЗЕРА (wipe)
# =========================================================

async def wipe_bot_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    """
    ЗАЧЕМ ЭТА ФУНКЦИЯ?

    Это главный "эффект исчезновения".

    Логика такая:
    1) Мы заранее сохраняем в БД все message_id,
       которые бот отправлял юзеру
    2) Когда юзер делает действие (нажимает кнопку)
       → удаляем все эти сообщения
    3) Чистим таблицу bot_messages, чтобы список был пустой

    РЕЗУЛЬТАТ:
    В чате у юзера не копится мусор из экранов.
    """
    message_ids = db.get_bot_messages(user_id)

    for mid in message_ids:
        await safe_delete_message(context, chat_id, mid)

    # После удаления — чистим список в базе
    db.clear_bot_messages(user_id)


# =========================================================
# 4) ОТПРАВКА ЭКРАНА (текст + кнопки) + сохранение message_id
# =========================================================

async def send_screen(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    text: str,
    keyboard: InlineKeyboardMarkup,
    *,
    wipe_before: bool = True,
    delete_clicked: bool = True,
    parse_mode: str = ParseMode.HTML,
    disable_preview: bool = True,
):
    """
    ЭТО САМАЯ ВАЖНАЯ ФУНКЦИЯ UI.

    ЧТО ОНА ДЕЛАЕТ:
    1) (опционально) удаляет сообщение, по которому нажали
       delete_clicked=True → сообщение с кнопкой исчезает
    2) (опционально) удаляет ВСЕ старые сообщения бота
       wipe_before=True → остается только 1 новый экран
    3) отправляет новый экран
    4) сохраняет message_id в базу, чтобы потом его удалить

    ЗАЧЕМ ПАРАМЕТРЫ:
    - wipe_before: иногда тебе надо НЕ удалять старые экраны (редко)
    - delete_clicked: иногда кнопка может быть "без удаления" (ты просил выбор)
    """

    chat_id = update.effective_chat.id

    # 1) удаляем сообщение по которому нажали (если это callback)
    if delete_clicked and update.callback_query:
        await delete_clicked_message(update)

    # 2) удаляем все старые экраны бота (эффект исчезновения)
    if wipe_before:
        await wipe_bot_messages(context, chat_id, user_id)

    # 3) отправляем новый экран
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_preview,
    )

    # 4) сохраняем id сообщения чтобы потом удалить
    db.add_bot_message(user_id, msg.message_id)

    return msg


# =========================================================
# 5) ОТПРАВКА НАПОМИНАНИЯ (оно тоже должно удаляться потом)
# =========================================================

async def send_reminder(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    text: str,
    keyboard: InlineKeyboardMarkup,
    *,
    parse_mode: str = ParseMode.HTML,
    disable_preview: bool = True,
):
    """
    ЗАЧЕМ ЭТА ФУНКЦИЯ?

    Напоминание — это обычное сообщение бота.
    Ты хотел, чтобы:
    ✅ оно тоже удалялось при следующем действии
    ✅ и удалялось сразу, если юзер нажал кнопку прямо на напоминании

    Поэтому:
    - мы его отправляем
    - сохраняем message_id в базу как обычный экран
    """
    msg = await context.bot.send_message(
        chat_id=user_id,
        text=text,
        reply_markup=keyboard,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_preview,
    )

    db.add_bot_message(user_id, msg.message_id)
    return msg
