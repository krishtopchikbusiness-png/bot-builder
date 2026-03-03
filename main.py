"""
main.py
ЗАЧЕМ:
- FastAPI сервер на Railway.
- При старте:
  1) Подключает Postgres
  2) Создаёт таблицы
  3) Ставит webhook для builder-бота
- Имеет 2 endpoint:
  /tg/builder/<secret>              апдейты builder-бота (платформа)
  /tg/client/<secret>/<bot_id>      апдейты клиентских ботов (которые подключили клиенты)

ЭТО = самый стабильный вариант для Railway.
"""

from fastapi import FastAPI, Request, HTTPException
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

import db
import builder
import client_runtime
from config import (
    BOT_TOKEN,
    DATABASE_URL,
    BUILDER_WEBHOOK_PATH,
    BUILDER_WEBHOOK_URL,
    WEBHOOK_SECRET,
)

api = FastAPI()
app: Application | None = None

@api.on_event("startup")
async def on_startup():
    global app
    # 1) база
    await db.init_pool(DATABASE_URL)
    await db.init_db()

    # 2) builder-бот (платформа) — telegram application
    app = Application.builder().token(BOT_TOKEN).build()

    # команды
    app.add_handler(CommandHandler("start", builder.start))

    # кнопки
    app.add_handler(CallbackQueryHandler(builder.on_callback))

    # текстовые сообщения (ввод токена, создание блока, текст блока и т.д.)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, builder.on_text))

    # 3) запускаем приложение в фоне (для обработки update'ов вручную)
    await app.initialize()
    await app.start()

    # 4) ставим webhook для builder-бота
    try:
        await app.bot.set_webhook(url=BUILDER_WEBHOOK_URL)
        print("✅ Builder webhook set:", BUILDER_WEBHOOK_URL)
    except Exception as e:
        print("❌ Не смог поставить webhook builder-боту:", e)

@api.on_event("shutdown")
async def on_shutdown():
    global app
    if app:
        await app.stop()
        await app.shutdown()

@api.post(BUILDER_WEBHOOK_PATH)
async def telegram_builder_webhook(request: Request):
    """
    Сюда Telegram присылает апдейты builder-бота.
    """
    if app is None:
        raise HTTPException(status_code=503, detail="Bot app not ready")

    data = await request.json()
    update = Update.de_json(data, app.bot)
    await app.process_update(update)
    return {"ok": True}

@api.post(f"/tg/client/{WEBHOOK_SECRET}/{{bot_id}}")
async def telegram_client_webhook(bot_id: int, request: Request):
    """
    Сюда Telegram присылает апдейты клиентских ботов (когда ты нажал Publish).
    """
    data = await request.json()
    await client_runtime.handle_client_update(bot_id, data)
    return {"ok": True}

@api.get("/")
async def root():
    return {"status": "running"}
