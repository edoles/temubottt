import asyncio
import logging
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

# ========== НАСТРОЙКИ ==========

BOT_TOKEN = " ВСТАВИТЬ ТОКЕН ПОТОМ"
ADMIN_ID = 8765864563
SUPPORT_USERNAME = "fainaler"
GROUP_URL = "https://t.me/temu_dopomogaaa"

PAYMENT_CARD = "5168752129855212"

SCHEME_PRICE = 300
FINISH_LINK_PRICE = 350

NEW_USERS_PRICES = {
    5: 160,
    6: 190,
    7: 220,
    8: 250,
    9: 299,
    10: 280,
}

SCHEME_TEXT = "Связь по схеме: @fainaler"
DB_NAME = "bot_orders.sqlite3"

logging.basicConfig(level=logging.INFO)

if "ВСТАВЬ_" in BOT_TOKEN or not BOT_TOKEN.strip():
    raise ValueError("Вставь токен от BotFather в BOT_TOKEN")

session = AiohttpSession(timeout=60)
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher()


# ========== БАЗА ДАННЫХ ==========

db = sqlite3.connect(DB_NAME)
db.row_factory = sqlite3.Row

db.execute("""
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT,
    service TEXT NOT NULL,
    price INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'waiting_receipt',
    created_at TEXT NOT NULL,
    link TEXT DEFAULT ''
)
""")

columns = {
    row["name"] for row in db.execute("PRAGMA table_info(orders)")
}
if "link" not in columns:
    db.execute("ALTER TABLE orders ADD COLUMN link TEXT DEFAULT ''")
db.commit()


def create_order(user, service, price, status="waiting_receipt"):
    cur = db.execute("""
        INSERT INTO orders
        (user_id, username, service, price, status, created_at, link)
        VALUES (?, ?, ?, ?, ?, ?, '')
    """, (
        user.id, user.username or "", service, price, status,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    db.commit()
    return cur.lastrowid


def get_order(order_id):
    return db.execute(
        "SELECT * FROM orders WHERE id = ?", (order_id,)
    ).fetchone()


def set_order_status(order_id, status):
    db.execute(
        "UPDATE orders SET status = ? WHERE id = ?",
        (status, order_id)
    )
    db.commit()


def get_orders(status=None, limit=20):
    if status:
        return db.execute("""
            SELECT * FROM orders WHERE status = ?
            ORDER BY id DESC LIMIT ?
        """, (status, limit)).fetchall()

    return db.execute("""
        SELECT * FROM orders ORDER BY id DESC LIMIT ?
    """, (limit,)).fetchall()


def is_admin(user_id):
    return user_id == ADMIN_ID


# ========== CALLBACK: БЕЗОПАСНЫЙ ОТВЕТ ==========

async def safe_answer(call, text=None, show_alert=False):
    try:
        await call.answer(text=text, show_alert=show_alert)
    except TelegramBadRequest as exc:
        error = str(exc).lower()
        if "query is too old" in error or "query id is invalid" in error:
            logging.warning("Устаревший callback — продолжаю обработку.")
        else:
            raise


# ========== КЛАВИАТУРЫ ==========

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="👥 Новые пользователи",
            callback_data="service_users")],
        [InlineKeyboardButton(
            text="📋 Схема",
            callback_data="service_scheme")],
        [InlineKeyboardButton(
            text="🔗 Финиш-ссылка",
            callback_data="service_finish")],
        [InlineKeyboardButton(
            text="💬 Поддержка",
            url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton(
            text="📢 Наша группа", url=GROUP_URL)],
    ])


def quantity_menu():
    rows = [
        [InlineKeyboardButton(
            text=f"{qty} шт. — {price} грн",
            callback_data=f"quantity_{qty}")]
        for qty, price in NEW_USERS_PRICES.items()
    ]
    rows.append([InlineKeyboardButton(
        text="⬅️ Главное меню", callback_data="go_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_menu(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Я оплатил",
            callback_data=f"paid_{order_id}")],
        [InlineKeyboardButton(
            text="⬅️ Главное меню", callback_data="go_menu")],
    ])


def admin_order_menu(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Одобрить", callback_data=f"approve_{order_id}"),
        InlineKeyboardButton(
            text="❌ Отклонить", callback_data=f"reject_{order_id}"),
    ]])


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📦 Все заказы", callback_data="admin_orders")],
        [InlineKeyboardButton(
            text="⏳ Ожидают проверки", callback_data="admin_pending")],
        [InlineKeyboardButton(
            text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(
            text="⬅️ Главное меню", callback_data="go_menu")],
    ])


# ========== ОПЛАТА ==========

async def show_payment(message, order_id):
    order = get_order(order_id)
    if not order:
        await message.answer("Заказ не найден. Напиши /start.")
        return

    link_text = f"Ссылка: {order['link']}\n\n" if order["link"] else ""

    await message.answer(
        f"🧾 Заказ №{order_id}\n\n"
        f"Услуга: {order['service']}\n"
        f"Стоимость: {order['price']} грн\n"
        f"{link_text}"
        f"💳 Реквизиты для оплаты:\n{PAYMENT_CARD}\n\n"
        "После оплаты нажми «Я оплатил» и отправь фото квитанции "
        "или документ.\n"
        "Оплата проверяется администратором вручную.",
        reply_markup=payment_menu(order_id)
    )


# ========== СТАРТ И КОМАНДЫ ==========

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Добро пожаловать!\n\nВыбери услугу в меню ниже.",
        reply_markup=main_menu()
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "📖 Команды:\n"
        "/start — главное меню\n"
        "/cancel — отменить ожидание\n"
        "/help — помощь\n"
        "/admin — панель администратора\n"
        f"Поддержка: @{SUPPORT_USERNAME}",
        reply_markup=main_menu()
    )


@dp.message(Command("cancel"))
async def cancel(message: Message):
    db.execute("""
        UPDATE orders SET status = 'cancelled'
        WHERE user_id = ?
        AND status IN ('awaiting_link', 'awaiting_receipt_upload')
    """, (message.from_user.id,))
    db.commit()
    await message.answer("Ожидание отменено.", reply_markup=main_menu())


# ========== МЕНЮ ==========

@dp.callback_query(F.data == "go_menu")
async def go_menu(call: CallbackQuery):
    await safe_answer(call)
    await call.message.answer("Главное меню:", reply_markup=main_menu())


# ========== НОВЫЕ ПОЛЬЗОВАТЕЛИ ==========

@dp.callback_query(F.data == "service_users")
async def service_users(call: CallbackQuery):
    await safe_answer(call)
    await call.message.answer(
        "👥 Выбери количество:", reply_markup=quantity_menu()
    )


@dp.callback_query(F.data.startswith("quantity_"))
async def select_quantity(call: CallbackQuery):
    await safe_answer(call)

    try:
        qty = int(call.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await call.message.answer("Ошибка количества.")
        return

    if qty not in NEW_USERS_PRICES:
        await call.message.answer("Такого варианта нет.")
        return

    order_id = create_order(
        call.from_user,
        f"Новые пользователи: {qty}",
        NEW_USERS_PRICES[qty],
        status="awaiting_link"
    )
    await call.message.answer(
        f"👥 Заказ №{order_id}\n\n"
        f"Количество: {qty}\n"
        f"Стоимость: {NEW_USERS_PRICES[qty]} грн\n\n"
        "🔗 Теперь отправь ссылку одним сообщением.\n"
        "Для отмены используй /cancel."
    )


# ========== ФИНИШ-ССЫЛКА ==========

@dp.callback_query(F.data == "service_finish")
async def service_finish(call: CallbackQuery):
    await safe_answer(call)

    order_id = create_order(
        call.from_user, "Финиш-ссылка", FINISH_LINK_PRICE,
        status="awaiting_link"
    )
    await call.message.answer(
        f"🔗 Заказ №{order_id}\n\n"
        f"Стоимость: {FINISH_LINK_PRICE} грн\n\n"
        "Отправь ссылку одним сообщением.\n"
        "Для отмены используй /cancel."
    )


# ========== СХЕМА: СРАЗУ ОПЛАТА ==========

@dp.callback_query(F.data == "service_scheme")
async def service_scheme(call: CallbackQuery):
    await safe_answer(call)

    order_id = create_order(
        call.from_user, "Схема", SCHEME_PRICE,
        status="waiting_receipt"
    )
    await show_payment(call.message, order_id)


# ========== ПРИЁМ ССЫЛОК ==========

@dp.message(F.text)
async def receive_text(message: Message):
    text = (message.text or "").strip()
    if text.startswith("/"):
        return

    order = db.execute("""
        SELECT * FROM orders
        WHERE user_id = ? AND status = 'awaiting_link'
        ORDER BY id DESC LIMIT 1
    """, (message.from_user.id,)).fetchone()

    if not order:
        await message.answer("Выбери услугу:", reply_markup=main_menu())
        return

    if not text.startswith(("https://", "http://", "t.me/", "www.")):
        await message.answer(
            "⚠️ Отправь ссылку, начинающуюся с https:// или http://."
        )
        return

    db.execute(
        "UPDATE orders SET link = ?, status = 'waiting_receipt' WHERE id = ?",
        (text, order["id"])
    )
    db.commit()
    await show_payment(message, order["id"])


# ========== Я ОПЛАТИЛ ==========

@dp.callback_query(F.data.startswith("paid_"))
async def paid(call: CallbackQuery):
    await safe_answer(call)

    try:
        order_id = int(call.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await call.message.answer("Ошибка номера заказа.")
        return

    order = get_order(order_id)
    if not order or order["user_id"] != call.from_user.id:
        await call.message.answer("Заказ не найден.")
        return

    if order["status"] != "waiting_receipt":
        await call.message.answer(
            "Заказ уже обрабатывается или отменён."
        )
        return

    set_order_status(order_id, "awaiting_receipt_upload")
    await call.message.answer(
        f"📸 Отправь фото квитанции или документ по заказу №{order_id}."
    )


# ========== ПРИЁМ КВИТАНЦИЙ ==========

@dp.message(F.photo | F.document)
async def receive_receipt(message: Message):
    order = db.execute("""
        SELECT * FROM orders
        WHERE user_id = ? AND status = 'awaiting_receipt_upload'
        ORDER BY id DESC LIMIT 1
    """, (message.from_user.id,)).fetchone()

    if not order:
        await message.answer(
            "Сначала выбери услугу, оплати и нажми «Я оплатил»."
        )
        return

    order_id = order["id"]
    caption = (
        f"🧾 НОВАЯ КВИТАНЦИЯ\n"
        f"Заказ №{order_id}\n"
        f"Пользователь ID: {order['user_id']}\n"
        f"Username: @{order['username'] or 'не указан'}\n"
        f"Услуга: {order['service']}\n"
        f"Сумма: {order['price']} грн\n"
        f"Ссылка: {order['link'] or 'не требуется'}"
    )

    try:
        if message.photo:
            await bot.send_photo(
                chat_id=ADMIN_ID,
                photo=message.photo[-1].file_id,
                caption=caption,
                reply_markup=admin_order_menu(order_id)
            )
        else:
            await bot.send_document(
                chat_id=ADMIN_ID,
                document=message.document.file_id,
                caption=caption,
                reply_markup=admin_order_menu(order_id)
            )

        set_order_status(order_id, "review")
        await message.answer(
            "✅ Квитанция отправлена администратору. Ожидай проверки."
        )
    except Exception:
        logging.exception("Ошибка передачи квитанции админу")
        await message.answer(
            "Не удалось передать квитанцию. "
            f"Обратись к @{SUPPORT_USERNAME}."
        )


# ========== ОДОБРЕНИЕ ЗАКАЗА ==========

@dp.callback_query(F.data.startswith("approve_"))
async def approve_order(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await safe_answer(call, "Нет доступа.", show_alert=True)
        return

    await safe_answer(call)

    try:
        order_id = int(call.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await call.message.answer("Неверный номер заказа.")
        return

    order = get_order(order_id)
    if not order or order["status"] != "review":
        await call.message.answer(
            "Заказ не найден или уже обработан."
        )
        return

    if order["service"] == "Схема":
        result = "✅ Оплата схемы одобрена!\n\n" + SCHEME_TEXT
    else:
        result = (
            f"✅ Оплата заказа №{order_id} одобрена!\n\n"
            f"Услуга: {order['service']}\n"
            f"Твоя ссылка: {order['link'] or 'не требуется'}\n"
            f"По вопросам: @{SUPPORT_USERNAME}"
        )

    try:
        await bot.send_message(order["user_id"], result)
    except Exception:
        logging.exception("Не удалось написать покупателю")
        await call.message.answer(
            "Не удалось написать покупателю. "
            "Пусть он откроет бота и нажмёт /start."
        )
        return

    set_order_status(order_id, "approved")
    await call.message.answer(f"✅ Заказ №{order_id} одобрен.")


# ========== ОТКЛОНЕНИЕ ЗАКАЗА ==========

@dp.callback_query(F.data.startswith("reject_"))
async def reject_order(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await safe_answer(call, "Нет доступа.", show_alert=True)
        return

    await safe_answer(call)

    try:
        order_id = int(call.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await call.message.answer("Неверный номер заказа.")
        return

    order = get_order(order_id)
    if not order or order["status"] != "review":
        await call.message.answer(
            "Заказ не найден или уже обработан."
        )
        return

    try:
        await bot.send_message(
            order["user_id"],
            f"❌ Квитанция по заказу №{order_id} отклонена.\n"
            f"Связь с администратором: @{SUPPORT_USERNAME}"
        )
    except Exception:
        logging.exception("Не удалось уведомить покупателя")

    set_order_status(order_id, "rejected")
    await call.message.answer(f"❌ Заказ №{order_id} отклонён.")


# ========== АДМИН-ПАНЕЛЬ ==========

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа.")
        return

    await message.answer(
        "🛠 Панель администратора", reply_markup=admin_menu()
    )


@dp.callback_query(F.data == "admin_orders")
async def admin_orders(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await safe_answer(call, "Нет доступа.", show_alert=True)
        return

    await safe_answer(call)
    orders = get_orders(limit=20)

    if not orders:
        await call.message.answer("Заказов пока нет.")
        return

    for order in orders:
        text = (
            f"🧾 Заказ №{order['id']}\n"
            f"ID: {order['user_id']}\n"
            f"Услуга: {order['service']}\n"
            f"Цена: {order['price']} грн\n"
            f"Статус: {order['status']}\n"
            f"Ссылка: {order['link'] or 'не требуется'}"
        )
        markup = (
            admin_order_menu(order["id"])
            if order["status"] == "review" else None
        )
        await call.message.answer(text, reply_markup=markup)


@dp.callback_query(F.data == "admin_pending")
async def admin_pending(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await safe_answer(call, "Нет доступа.", show_alert=True)
        return

    await safe_answer(call)
    orders = get_orders(status="review", limit=30)

    if not orders:
        await call.message.answer("⏳ Заказов на проверке нет.")
        return

    for order in orders:
        await call.message.answer(
            f"🧾 Заказ №{order['id']}\n"
            f"Пользователь: {order['user_id']}\n"
            f"Услуга: {order['service']}\n"
            f"Сумма: {order['price']} грн",
            reply_markup=admin_order_menu(order["id"])
        )


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await safe_answer(call, "Нет доступа.", show_alert=True)
        return

    await safe_answer(call)

    total = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    pending = db.execute(
        "SELECT COUNT(*) FROM orders WHERE status = 'review'"
    ).fetchone()[0]
    approved = db.execute(
        "SELECT COUNT(*) FROM orders WHERE status = 'approved'"
    ).fetchone()[0]
    rejected = db.execute(
        "SELECT COUNT(*) FROM orders WHERE status = 'rejected'"
    ).fetchone()[0]
    revenue = db.execute(
        "SELECT COALESCE(SUM(price), 0) FROM orders WHERE status = 'approved'"
    ).fetchone()[0]

    await call.message.answer(
        f"📊 Статистика\n\n"
        f"Всего заказов: {total}\n"
        f"Ожидают проверки: {pending}\n"
        f"Одобрено: {approved}\n"
        f"Отклонено: {rejected}\n"
        f"Доход: {revenue} грн"
    )


# ========== ЗАПУСК ==========

async def main():
    print("Бот запускается...")
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        print("Бот запущен и ожидает сообщения!")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
    except Exception:
        logging.exception("Ошибка запуска бота")
    finally:
        db.close()
