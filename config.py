"""
config.py
ЗАЧЕМ:
- Все настройки в одном месте.
- Если переменной нет — сразу понятная ошибка.

Railway Variables:
- BOT_TOKEN
- WEBHOOK_BASE_URL
- WEBHOOK_SECRET
- DATABASE_URL
"""

import os

def must(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"❌ Не задана переменная окружения: {name}")
    return v

BOT_TOKEN = must("BOT_TOKEN")
WEBHOOK_BASE_URL = must("WEBHOOK_BASE_URL").rstrip("/")
WEBHOOK_SECRET = must("WEBHOOK_SECRET")
DATABASE_URL = must("DATABASE_URL")

# Webhook для builder-бота (тот, который ты админишь как платформу)
BUILDER_WEBHOOK_PATH = f"/tg/builder/{WEBHOOK_SECRET}"
BUILDER_WEBHOOK_URL = f"{WEBHOOK_BASE_URL}{BUILDER_WEBHOOK_PATH}"

# Webhook для клиентских ботов (которые подключают клиенты)
CLIENT_WEBHOOK_PATH_PREFIX = f"/tg/client/{WEBHOOK_SECRET}"  # дальше добавим /{bot_id}
