"""
builder.py
ЗАЧЕМ:
- Это логика builder-бота (тот, с которым клиент управляет своими ботами).
- Здесь все экраны: welcome → мои боты → подключить → конструктор → блоки → кнопки.
- Здесь же принимаем текстовые вводы (токен, название блока, текст блока, текст кнопки...).

ВАЖНО:
- Builder бот живёт на webhook (его настраивает main.py).
"""

from telegram import Update
from telegram.ext import ContextTypes
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import TelegramError
from telegram import Bot as TgBot

import db
import ui
from config import WEBHOOK_BASE_URL, CLIENT_WEBHOOK_PATH_PREFIX, WEBHOOK_SECRET

# -----------------------------
# Тексты экранов (меняй как хочешь)
# -----------------------------

WELCOME_TEXT = (
    "🧩 <b>Конструктор Telegram-ботов</b>\n\n"
    "Создайте бота без кода.\n"
    "Подключите токен BotFather и собирайте блоки как ManyChat.\n\n"
    "Нажмите «Мои боты»."
)

CONNECT_TEXT = (
    "➕ <b>Подключение бота</b>\n\n"
    "1) Откройте @BotFather\n"
    "2) Создайте бота (/newbot)\n"
    "3) Скопируйте токен\n"
    "4) Отправьте токен одним сообщением сюда\n\n"
    "⚠️ Токен должен выглядеть примерно так:\n"
    "<code>123456:ABCdef...</code>"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    await db.upsert_platform_user(user_id)

    await db.set_platform_state(user_id, screen="welcome", prev_screen=None, pending_type=None, pending_payload=None)
    await ui.send_screen(
        chat_id=chat_id,
        user_id=user_id,
        context=context,
        text=WELCOME_TEXT,
        keyboard=ui.kb_main(),
        delete_prev=True
    )

# -----------------------------
# Навигация (кнопки)
# -----------------------------

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    await db.upsert_platform_user(user_id)

    data = q.data or ""

    # Главное меню
    if data == "nav:main":
        await db.set_platform_state(user_id, screen="welcome", pending_type=None, pending_payload=None)
        await ui.send_screen(chat_id=chat_id, user_id=user_id, context=context, text=WELCOME_TEXT, keyboard=ui.kb_main(), delete_prev=True)
        return

    # Мои боты
    if data == "nav:my_bots":
        bots = await db.list_client_bots(user_id)
        text = "🤖 <b>Мои боты</b>\n\n" + ("Выберите бота или подключите нового." if bots else "У вас пока нет ботов. Подключите первого.")
        await db.set_platform_state(user_id, screen="my_bots", pending_type=None, pending_payload=None)
        await ui.send_screen(chat_id=chat_id, user_id=user_id, context=context, text=text, keyboard=ui.kb_bots_list(bots), delete_prev=True)
        return

    # Подключить бота
    if data == "nav:connect_bot":
        await db.set_platform_state(user_id, screen="connect_bot", pending_type="await_bot_token", pending_payload={}, prev_screen="my_bots")
        await ui.send_screen(chat_id=chat_id, user_id=user_id, context=context, text=CONNECT_TEXT, keyboard=ui.kb_back_and_home("nav:my_bots"), delete_prev=True)
        return

    # Открыть бот
    if data.startswith("bot:open:"):
        bot_id = int(data.split(":")[-1])
        bot = await db.get_client_bot(bot_id)
        if not bot or bot["owner_id"] != user_id:
            await ui.send_screen(chat_id=chat_id, user_id=user_id, context=context, text="❌ Бот не найден.", keyboard=ui.kb_main(), delete_prev=True)
            return
        text = (
            f"🤖 <b>@{bot.get('bot_username') or 'unknown'}</b>\n"
            f"Статус: {'✅ Опубликован' if bot.get('published') else '📝 Черновик'}\n\n"
            "Выберите действие:"
        )
        await db.set_platform_state(user_id, screen="bot_panel", pending_type=None, pending_payload=None, prev_screen="my_bots")
        await ui.send_screen(chat_id=chat_id, user_id=user_id, context=context, text=text, keyboard=ui.kb_open_bot(bot_id), delete_prev=True)
        return

    # Открыть конструктор (flow)
    if data.startswith("flow:open:"):
        bot_id = int(data.split(":")[-1])
        await db.set_platform_state(user_id, screen="flow", pending_type=None, pending_payload=None, prev_screen=f"bot:{bot_id}")
        await ui.send_screen(
            chat_id=chat_id,
            user_id=user_id,
            context=context,
            text=f"🧩 <b>Конструктор</b>\n\nБот ID: <code>{bot_id}</code>\n\nВыберите действие:",
            keyboard=ui.kb_flow_home(bot_id),
            delete_prev=True
        )
        return

    # Список блоков
    if data.startswith("flow:list_blocks:"):
        bot_id = int(data.split(":")[-1])
        blocks = await db.list_blocks(bot_id)
        await db.set_platform_state(user_id, screen="blocks_list", pending_type=None, pending_payload=None, prev_screen=f"flow:{bot_id}")
        await ui.send_screen(
            chat_id=chat_id,
            user_id=user_id,
            context=context,
            text="📋 <b>Блоки</b>\n\n🧽 = удаляет предыдущее сообщение\n📌 = не удаляет",
            keyboard=ui.kb_blocks_list(bot_id, blocks),
            delete_prev=True
        )
        return

    # Новый блок
    if data.startswith("flow:new_block:"):
        bot_id = int(data.split(":")[-1])
        await db.set_platform_state(
            user_id,
            screen="new_block",
            pending_type="await_block_name",
            pending_payload={"bot_id": bot_id},
            prev_screen=f"flow:list_blocks:{bot_id}"
        )
        await ui.send_screen(
            chat_id=chat_id,
            user_id=user_id,
            context=context,
            text="➕ <b>Новый блок</b>\n\nОтправьте название блока одним сообщением.",
            keyboard=ui.kb_back_and_home(f"flow:list_blocks:{bot_id}"),
            delete_prev=True
        )
        return

    # Открыть блок (редактор)
    if data.startswith("block:open:"):
        _, _, bot_id, block_id = data.split(":")
        bot_id = int(bot_id)
        block_id = int(block_id)
        block = await db.get_block(block_id)
        if not block:
            await ui.send_screen(chat_id=chat_id, user_id=user_id, context=context, text="❌ Блок не найден.", keyboard=ui.kb_main(), delete_prev=True)
            return

        buttons = await db.list_buttons(block_id)
        btn_lines = []
        for b in buttons:
            if b["action_type"] == "go_block":
                btn_lines.append(f"• {b['title']} → блок #{b['action_value']}")
            elif b["action_type"] == "open_url":
                btn_lines.append(f"• {b['title']} → ссылка")
            else:
                btn_lines.append(f"• {b['title']} → текст")

        text = (
            f"🧱 <b>Блок:</b> {block['title']}\n"
            f"{'🧽 Удаляет предыдущее' if block['delete_prev'] else '📌 Не удаляет предыдущее'}\n\n"
            f"📝 <b>Текст:</b>\n{block['text'] or '(пусто)'}\n\n"
            f"🔘 <b>Кнопки:</b>\n" + ("\n".join(btn_lines) if btn_lines else "—")
        )

        await db.set_platform_state(user_id, screen="block_editor", pending_type=None, pending_payload=None, prev_screen=f"flow:list_blocks:{bot_id}")
        await ui.send_screen(
            chat_id=chat_id,
            user_id=user_id,
            context=context,
            text=text,
            keyboard=ui.kb_block_editor(bot_id, block_id, block["delete_prev"]),
            delete_prev=True
        )
        return

    # Переключить delete_prev у блока
    if data.startswith("block:toggle_del:"):
        _, _, bot_id, block_id = data.split(":")
        bot_id = int(bot_id)
        block_id = int(block_id)
        await db.toggle_block_delete_prev(block_id)
        # просто переоткроем блок
        await on_callback(update, context= context._replace() )  # не используется, оставим ниже правильный переход
        return

    # Редактировать текст блока
    if data.startswith("block:edit_text:"):
        _, _, bot_id, block_id = data.split(":")
        bot_id = int(bot_id)
        block_id = int(block_id)
        await db.set_platform_state(
            user_id,
            screen="edit_block_text",
            pending_type="await_block_text",
            pending_payload={"bot_id": bot_id, "block_id": block_id},
            prev_screen=f"block:open:{bot_id}:{block_id}"
        )
        await ui.send_screen(
            chat_id=chat_id,
            user_id=user_id,
            context=context,
            text="✏️ <b>Новый текст блока</b>\n\nОтправьте новый текст одним сообщением.",
            keyboard=ui.kb_back_and_home(f"block:open:{bot_id}:{block_id}"),
            delete_prev=True
        )
        return

    # Добавить кнопку (шаг 1: название)
    if data.startswith("btn:add:"):
        _, _, bot_id, block_id = data.split(":")
        bot_id = int(bot_id)
        block_id = int(block_id)
        await db.set_platform_state(
            user_id,
            screen="add_button_title",
            pending_type="await_button_title",
            pending_payload={"bot_id": bot_id, "block_id": block_id},
            prev_screen=f"block:open:{bot_id}:{block_id}"
        )
        await ui.send_screen(
            chat_id=chat_id,
            user_id=user_id,
            context=context,
            text="➕ <b>Новая кнопка</b>\n\nОтправьте текст кнопки одним сообщением.",
            keyboard=ui.kb_back_and_home(f"block:open:{bot_id}:{block_id}"),
            delete_prev=True
        )
        return

    # Выбор типа действия кнопки
    if data.startswith("btn:act:"):
        # btn:act:go_block:bot_id:block_id
        parts = data.split(":")
        action = parts[2]
        bot_id = int(parts[3])
        block_id = int(parts[4])

        st = await db.get_platform_state(user_id)
        pending = st.get("pending_payload") or {}
        btn_title = pending.get("btn_title")
        if not btn_title:
            await ui.send_screen(chat_id=chat_id, user_id=user_id, context=context, text="❌ Нет названия кнопки. Создайте заново.", keyboard=ui.kb_main(), delete_prev=True)
            return

        if action == "go_block":
            # попросим выбрать цель
            blocks = await db.list_blocks(bot_id)
            rows = []
            for bl in blocks:
                rows.append([InlineKeyboardButton(f"🧱 {bl['title']} (#{bl['id']})", callback_data=f"btn:set_target:{bot_id}:{block_id}:{bl['id']}")])
            rows.append([InlineKeyboardButton("➕ Создать новый блок", callback_data=f"flow:new_block:{bot_id}")])
            rows.append([InlineKeyboardButton("⬅ Назад", callback_data=f"block:open:{bot_id}:{block_id}")])
            await ui.send_screen(
                chat_id=chat_id, user_id=user_id, context=context,
                text="➡️ <b>Куда ведёт кнопка?</b>\nВыберите блок:",
                keyboard=InlineKeyboardMarkup(rows),
                delete_prev=True
            )
            return

        if action == "open_url":
            await db.set_platform_state(
                user_id,
                screen="await_url",
                pending_type="await_button_url",
                pending_payload={"bot_id": bot_id, "block_id": block_id, "btn_title": btn_title},
                prev_screen=f"block:open:{bot_id}:{block_id}"
            )
            await ui.send_screen(
                chat_id=chat_id, user_id=user_id, context=context,
                text="🔗 <b>Ссылка</b>\n\nОтправьте URL одним сообщением.",
                keyboard=ui.kb_back_and_home(f"block:open:{bot_id}:{block_id}"),
                delete_prev=True
            )
            return

        if action == "send_text":
            await db.set_platform_state(
                user_id,
                screen="await_send_text",
                pending_type="await_button_send_text",
                pending_payload={"bot_id": bot_id, "block_id": block_id, "btn_title": btn_title},
                prev_screen=f"block:open:{bot_id}:{block_id}"
            )
            await ui.send_screen(
                chat_id=chat_id, user_id=user_id, context=context,
                text="✉️ <b>Текст кнопки</b>\n\nОтправьте текст, который бот отправит при нажатии.",
                keyboard=ui.kb_back_and_home(f"block:open:{bot_id}:{block_id}"),
                delete_prev=True
            )
            return

    # установить цель go_block
    if data.startswith("btn:set_target:"):
        _, _, bot_id, block_id, target_block_id = data.split(":")
        bot_id = int(bot_id)
        block_id = int(block_id)
        target_block_id = int(target_block_id)

        st = await db.get_platform_state(user_id)
        pending = st.get("pending_payload") or {}
        btn_title = pending.get("btn_title")

        if not btn_title:
            await ui.send_screen(chat_id=chat_id, user_id=user_id, context=context, text="❌ Нет названия кнопки.", keyboard=ui.kb_main(), delete_prev=True)
            return

        await db.create_button(block_id, btn_title, "go_block", str(target_block_id))
        await db.set_platform_state(user_id, pending_type=None, pending_payload=None)
        await ui.send_screen(chat_id=chat_id, user_id=user_id, context=context, text="✅ Кнопка добавлена.", keyboard=ui.kb_back_and_home(f"block:open:{bot_id}:{block_id}"), delete_prev=True)
        return

    # publish
    if data.startswith("bot:publish:"):
        bot_id = int(data.split(":")[-1])
        bot = await db.get_client_bot(bot_id)
        if not bot or bot["owner_id"] != user_id:
            await ui.send_screen(chat_id=chat_id, user_id=user_id, context=context, text="❌ Бот не найден.", keyboard=ui.kb_main(), delete_prev=True)
            return

        # Ставим webhook клиентскому боту на наш сервер:
        # /tg/client/<secret>/<bot_id>
        client_webhook_url = f"{WEBHOOK_BASE_URL}{CLIENT_WEBHOOK_PATH_PREFIX}/{bot_id}"
        try:
            client_bot = TgBot(token=bot["bot_token"])
            ok = await client_bot.set_webhook(url=client_webhook_url)
            if not ok:
                raise TelegramError("setWebhook вернул False")
        except Exception as e:
            await ui.send_screen(
                chat_id=chat_id, user_id=user_id, context=context,
                text=f"❌ Не удалось опубликовать.\nПроверь токен/доступ.\n\nОшибка: <code>{e}</code>",
                keyboard=ui.kb_open_bot(bot_id),
                delete_prev=True
            )
            return

        await db.set_client_bot_published(bot_id, True)
        await ui.send_screen(
            chat_id=chat_id, user_id=user_id, context=context,
            text="🚀 <b>Опубликовано!</b>\n\nТеперь клиентский бот начнёт отвечать по блокам.",
            keyboard=ui.kb_open_bot(bot_id),
            delete_prev=True
        )
        return

    # toggle delete_prev fix: если нажали на кнопку toggle — мы должны переоткрыть блок
    if data.startswith("block:toggle_del:"):
        _, _, bot_id, block_id = data.split(":")
        bot_id = int(bot_id); block_id = int(block_id)
        await db.toggle_block_delete_prev(block_id)
        # переоткрываем блок
        q.data = f"block:open:{bot_id}:{block_id}"
        await on_callback(update, context)
        return

    # default
    await ui.send_screen(chat_id=chat_id, user_id=user_id, context=context, text="❌ Неизвестная команда.", keyboard=ui.kb_main(), delete_prev=True)

# -----------------------------
# Текстовые сообщения (вводы)
# -----------------------------

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    await db.upsert_platform_user(user_id)

    state = await db.get_platform_state(user_id)
    pending_type = state.get("pending_type")
    payload = state.get("pending_payload") or {}

    text = (update.message.text or "").strip()
    if not text:
        return

    # 1) ожидаем токен бота
    if pending_type == "await_bot_token":
        token = text
        # проверяем токен через getMe
        try:
            test_bot = TgBot(token=token)
            me = await test_bot.get_me()
            username = me.username or ""
            if not username:
                raise TelegramError("Не получил username")
        except Exception:
            await ui.send_screen(
                chat_id=chat_id, user_id=user_id, context=context,
                text="❌ Токен неверный. Проверь в BotFather и отправь снова.",
                keyboard=ui.kb_back_and_home("nav:connect_bot"),
                delete_prev=True
            )
            return

        bot_id = await db.create_client_bot(owner_id=user_id, token=token, username=username)
        await db.set_platform_state(user_id, pending_type=None, pending_payload=None)

        await ui.send_screen(
            chat_id=chat_id, user_id=user_id, context=context,
            text=f"✅ Бот подключён: <b>@{username}</b>\nID: <code>{bot_id}</code>\n\nОткрыть панель бота?",
            keyboard=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Открыть", callback_data=f"bot:open:{bot_id}")],
                [InlineKeyboardButton("🤖 Мои боты", callback_data="nav:my_bots")],
            ]),
            delete_prev=True
        )
        return

    # 2) ожидание названия блока
    if pending_type == "await_block_name":
        bot_id = int(payload["bot_id"])
        block_id = await db.create_block(bot_id, text)
        await db.set_platform_state(user_id, pending_type=None, pending_payload=None)
        await ui.send_screen(
            chat_id=chat_id, user_id=user_id, context=context,
            text="✅ Блок создан.",
            keyboard=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧱 Открыть блок", callback_data=f"block:open:{bot_id}:{block_id}")],
                [InlineKeyboardButton("📋 Список блоков", callback_data=f"flow:list_blocks:{bot_id}")],
            ]),
            delete_prev=True
        )
        return

    # 3) ожидание текста блока
    if pending_type == "await_block_text":
        bot_id = int(payload["bot_id"])
        block_id = int(payload["block_id"])
        await db.update_block_text(block_id, text)
        await db.set_platform_state(user_id, pending_type=None, pending_payload=None)
        await ui.send_screen(
            chat_id=chat_id, user_id=user_id, context=context,
            text="✅ Текст блока обновлён.",
            keyboard=ui.kb_back_and_home(f"block:open:{bot_id}:{block_id}"),
            delete_prev=True
        )
        return

    # 4) ожидание названия кнопки
    if pending_type == "await_button_title":
        bot_id = int(payload["bot_id"])
        block_id = int(payload["block_id"])
        await db.set_platform_state(
            user_id,
            pending_type=None,
            pending_payload={"bot_id": bot_id, "block_id": block_id, "btn_title": text}
        )
        await ui.send_screen(
            chat_id=chat_id, user_id=user_id, context=context,
            text="✅ Теперь выбери действие кнопки:",
            keyboard=ui.kb_button_action_choose(bot_id, block_id),
            delete_prev=True
        )
        return

    # 5) ожидание URL для кнопки
    if pending_type == "await_button_url":
        bot_id = int(payload["bot_id"])
        block_id = int(payload["block_id"])
        btn_title = payload["btn_title"]
        await db.create_button(block_id, btn_title, "open_url", text)
        await db.set_platform_state(user_id, pending_type=None, pending_payload=None)
        await ui.send_screen(
            chat_id=chat_id, user_id=user_id, context=context,
            text="✅ Кнопка добавлена (ссылка).",
            keyboard=ui.kb_back_and_home(f"block:open:{bot_id}:{block_id}"),
            delete_prev=True
        )
        return

    # 6) ожидание текста для кнопки send_text
    if pending_type == "await_button_send_text":
        bot_id = int(payload["bot_id"])
        block_id = int(payload["block_id"])
        btn_title = payload["btn_title"]
        await db.create_button(block_id, btn_title, "send_text", text)
        await db.set_platform_state(user_id, pending_type=None, pending_payload=None)
        await ui.send_screen(
            chat_id=chat_id, user_id=user_id, context=context,
            text="✅ Кнопка добавлена (текст).",
            keyboard=ui.kb_back_and_home(f"block:open:{bot_id}:{block_id}"),
            delete_prev=True
        )
        return

    # обычный ввод не в режиме ожидания
    await ui.send_screen(
        chat_id=chat_id, user_id=user_id, context=context,
        text="❌ Неверный ввод.\nНажми «Главное меню».",
        keyboard=ui.kb_main(),
        delete_prev=True
    )
