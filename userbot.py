import asyncio
import logging
import os
import re
from telethon import TelegramClient, events

logging.basicConfig(level=logging.INFO)

# ==== НАСТРОЙКИ USERBOT ====
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
SESSION_NAME = "userbot_session"

# ==== ТЕКСТЫ ====
TEXTS = {
    "ru": {
        "header": "Telegram",
        "offer": "Пользователь предлагает вам",
        "for_gift": "за подарок",
        "valid_for": "Оффер действителен ещё 6 ч. 0 мин.",
    },
    "en": {
        "header": "Telegram",
        "offer": "A user offers you",
        "for_gift": "for the gift",
        "valid_for": "Offer is valid for another 6 h. 0 min.",
    },
}


def parse_nft_link(url):
    url = (url or "").strip()
    for ch in ("\u00a0", "\u200b", "\u200f", "\u200e"):
        url = url.replace(ch, "")
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
    if args:
        first = args[0].lower().lstrip("/.")
        if first == "buy":
            args = args[1:]
    if len(args) < 3:
        return None
    return lang, args[0], args[1], args[2].upper()


def build_text(t, nft_title, amount, currency, nft_link):
    return (
        f"{t['header']}\n"
        f"{nft_title}\n\n"
        f"{t['offer']}\n"
        f"{amount} {currency} {t['for_gift']} {nft_link}.\n\n"
        f"{t['valid_for']}"
    )


# ==== КЛИЕНТ ====
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)


@client.on(events.NewMessage(outgoing=True))
async def handler(event):
    text = event.raw_text or ""

    # Слушаем только .buy и /buy
    if not (text.startswith(".buy") or text.startswith("/buy")):
        return

    # Игнорируем команды в Saved Messages и с самим собой
    if event.is_private and event.chat_id == event.sender_id:
        return

    # Игнорируем ботов
    if event.is_private:
        try:
            peer = await event.get_chat()
            if getattr(peer, "bot", False):
                return
        except Exception:
            pass

    parsed = parse_buy_args(text)
    if not parsed:
        return

    lang, nft_link, amount, currency = parsed
    t = TEXTS[lang]

    nft_data = parse_nft_link(nft_link)
    if not nft_data:
        return

    nft_title = nft_data["full"]
    new_text = build_text(t, nft_title, amount, currency, nft_link)

    logging.info(f"[USERBOT] Найдено: {text!r} в chat_id={event.chat_id}")

    try:
        # Удаляем исходное сообщение
        await event.delete()
        # Отправляем карточку от нашего имени
        await client.send_message(event.chat_id, new_text, link_preview=True)
        logging.info(f"[USERBOT] Отправлено: {new_text!r}")
    except Exception as e:
        logging.error(f"[USERBOT] Ошибка: {e}")


async def main():
    logging.info("=== USERBOT STARTED ===")
    await client.start()
    me = await client.get_me()
    logging.info(f"=== USERBOT авторизован как @{me.username} (id={me.id}) ===")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
