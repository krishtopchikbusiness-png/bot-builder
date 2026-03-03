# main.py
# =========================================================
# Зачем этот файл:
# - точка входа
# - подключает handlers
# - запускает polling
# =========================================================

import os
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import db
import client

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Нет BOT_TOKEN в Railway Variables")

def main():
    db.init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", client.cmd_start))
    app.add_handler(CallbackQueryHandler(client.on_callback, pattern=r"^go:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, client.on_text))

    print("✅ Bot started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

