"""
===========================================================
ФАЙЛ: main.py
===========================================================

ЗАЧЕМ ЭТОТ ФАЙЛ?

Это главный файл запуска.

Он делает 5 вещей:

1) Берёт BOT_TOKEN из Railway Variables
2) Инициализирует базу данных (создаёт таблицы)
3) Подключает обработчики:
   - /start
   - нажатия кнопок (callback_data)
   - обычные сообщения (текст)
4) Запускает бота (polling)
5) Ловит и печатает ошибки в лог Railway

ВАЖНО:
Мы запускаем polling (не webhook).
Railway запускает файл как worker.
===========================================================
"""

import os
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

import db
import client


# =========================================================
# 1) ЧИТАЕМ ТОКЕН
# =========================================================

"""
ЗАЧЕМ?

Токен не пишем в код.
Токен должен быть в Railway → Variables → BOT_TOKEN
"""

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ Нет BOT_TOKEN в Railway Variables")


# =========================================================
# 2) ОБРАБОТЧИК ОШИБОК
# =========================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """
    ЗАЧЕМ?

    Если бот падает из-за ошибки,
    Railway покажет её в логах.

    Так мы быстро понимаем что сломалось.
    """
    print("❌ ERROR:", context.error)


# =========================================================
# 3) MAIN — ЗАПУСК
# =========================================================

def main():
    """
    ЗАЧЕМ?

    Эта функция запускается при старте контейнера Railway.

    Внутри:
    - создаём таблицы
    - создаём приложение Telegram
    - навешиваем handlers
    - запускаем polling
    """

    # 1) Инициализируем базу (создаём таблицы если их нет)
    db.init_db()

    # 2) Создаём приложение Telegram
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # 3) Команды
    app.add_handler(CommandHandler("start", client.cmd_start))

    # 4) Нажатия кнопок (callback_data)
    # Мы ловим все кнопки, у которых callback_data начинается с "c:"
    app.add_handler(CallbackQueryHandler(client.on_callback, pattern=r"^c:"))

    # 5) Обычные сообщения пользователя (текст)
    # Сюда попадёт всё, что не команда (/start и т.д.)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, client.on_text))

    # 6) Ошибки
    app.add_error_handler(error_handler)

    print("✅ Bot started (polling)")

    # 7) Запуск
    app.run_polling(
        drop_pending_updates=True,  # удаляет старые обновления, чтобы не спамило
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()


