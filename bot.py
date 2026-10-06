import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command

BOT_TOKEN = "8647715988:AAG6mC5VwkbXTOOzTXPtXy16TC6bRCJDkhM"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Отправь `.buy` и любой текст — я заменю его.\n"
        "Пример: `.buy яблоко`"
    )


@dp.message(F.text.startswith(".buy"))
async def handle_buy(message: types.Message):
    # Текст после ".buy"
    user_text = message.text[4:].strip()

    # Если нужен только шаблон:
    # await message.answer("Привет мир, как дела?")

    # Если хочешь подставить текст пользователя:
    await message.answer(f"Привет мир, как дела?\n\nТы написал: {user_text}")


async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
