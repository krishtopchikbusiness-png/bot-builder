# main.py
# =========================================================
# ЗАЧЕМ ЭТО:
# - точка входа: запускает бота
# - подключает хендлеры клиента
# - инициализирует базу
# =========================================================

import os
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
import db as DB
import client


BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Нет BOT_TOKEN в Variables (Railway)")


def main():
    # 1) создаём таблицы (если нет)
    DB.init_db()

    # 2) запускаем PTB
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # 3) команды
    app.add_handler(CommandHandler("start", client.cmd_start))

    # 4) кнопки (callback)
    app.add_handler(CallbackQueryHandler(client.on_callback, pattern=r"^c:"))

    # 5) текст
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, client.on_text))

    print("✅ Bot started")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )


if __name__ == "__main__":
    main()
