import os
import logging
import requests
import signal
import sys
from aiohttp import web
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальные переменные для хранения состояния пользователей
USER_STATE = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    user = update.message.from_user
    await update.message.reply_text(
        f"Привет, {user.first_name}!\n"
        "Я помогу найти товары на Wildberries по ценам ниже указанной.\n\n"
        "Как пользоваться:\n"
        "1. Введи команду /setprice и укажи максимальную цену (например: /setprice 5000)\n"
        "2. Затем отправь мне название товара для поиска"
    )

async def set_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Установка целевой цены"""
    try:
        user_id = update.message.from_user.id
        price = float(context.args[0])

        if price <= 0:
            await update.message.reply_text("Цена должна быть больше 0!")
            return

        USER_STATE[user_id] = {"target_price": price}
        await update.message.reply_text(
            f"✅ Установлена целевая цена: {price} руб.\n"
            "Теперь отправь название товара для поиска."
        )

    except (IndexError, ValueError):
        await update.message.reply_text("Использование: /setprice <цена> (например: /setprice 2500)")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка текстовых сообщений с поисковым запросом"""
    user_id = update.message.from_user.id
    query = update.message.text.strip()

    # Проверяем, установлена ли цена
    if user_id not in USER_STATE or "target_price" not in USER_STATE[user_id]:
        await update.message.reply_text("⚠ Сначала установите целевую цену с помощью /setprice")
        return

    target_price = USER_STATE[user_id]["target_price"]

    await update.message.reply_text(f"🔍 Ищу товары по запросу: '{query}' до {target_price} руб...")

    try:
        # Поиск товаров на Wildberries
        products = search_wildberries(query)
        if not products:
            await update.message.reply_text(
                "😢 Товары не найдены. "
                "Возможно, ваш IP заблокирован Wildberries (особенно если используется Render.com)."
            )
            return

        # Фильтрация и сортировка результатов
        filtered_products = [p for p in products if p["price"] <= target_price]
        filtered_products.sort(key=lambda x: x["price"])

        if not filtered_products:
            await update.message.reply_text("😢 Нет товаров ниже указанной цены.")
            return

        # Формирование сообщения с результатами
        message = f"✅ Найдено {len(filtered_products)} подходящих товаров:\n\n"
        for i, product in enumerate(filtered_products[:5], 1):
            message += (
                f"{i}. {product['name']}\n"
                f"💵 Цена: {product['price']} ₽\n"
                f"⭐ Рейтинг: {product['rating']} | ✨ Отзывов: {product['feedbacks']}\n"
                f"🛒 [Купить]({product['link']})\n\n"
            )

        await update.message.reply_text(
            message,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.error(f"Ошибка при обработке запроса: {e}", exc_info=True)
        await update.message.reply_text("⚠ Произошла ошибка при поиске. Попробуйте позже.")

def search_wildberries(query: str) -> list:
    """
    Поиск товаров на Wildberries через мобильное API
    """
    url = "https://mobile-app.wildberries.ru/catalog/search"

    headers = {
        "User-Agent": "Wildberries/6.12.0 (iPhone; iOS 16.5; Scale/3.00)",
        "Accept": "application/json",
        "Accept-Language": "ru-RU;q=1.0",
        "Connection": "keep-alive",
        "Referer": "https://mobile-app.wildberries.ru/",
        "X-Requested-With": "XMLHttpRequest"
    }

    params = {
        "query": query.strip(),
        "page": 1,
        "sort": "popular",
        "lang": "ru",
        "locale": "ru",
        "curr": "rub",
        "version": "6.12.0",
        "device": "iPhone14,3"
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        
        logger.info(f"Wildberries API: статус {response.status_code}, URL: {response.url}")

        if response.status_code != 200:
            logger.error(f"Ошибка API: статус {response.status_code}, тело: {response.text[:300]}")
            return []

        # Проверка на антибот
        if not response.text.startswith("{"):
            logger.warning("Получен HTML — сработал антибот Wildberries")
            return []

        data = response.json()

        products_data = data.get("data", {}).get("products", [])
        if not products_data:
            logger.info(f"Нет товаров по запросу '{query}'")
            return []

        products = []
        for item in products_data[:20]:
            sale_price = item.get("salePriceU")
            if not sale_price:
                continue

            products.append({
                "name": item.get("name", "Без названия").strip(),
                "price": sale_price // 100,
                "rating": float(item.get("reviewRating", 0)),
                "feedbacks": int(item.get("feedbacks", 0)),
                "link": f"https://www.wildberries.ru/catalog/{item['id']}/detail.aspx"
            })

        logger.info(f"✅ Найдено {len(products)} товаров по запросу '{query}'")
        return products

    except Exception as e:
        logger.error(f"Ошибка при поиске: {e}", exc_info=True)
        return []

async def health_check(request):
    """Health check endpoint"""
    return web.Response(text="OK", status=200)

async def webhook_handler(request):
    """Обработчик входящих вебхуков от Telegram"""
    application = request.app['application']
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return web.Response()

async def main():
    """Запуск бота в режиме Webhook"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    webhook_url = os.getenv("RENDER_EXTERNAL_URL")  # например: https://tg-bot-ccn2.onrender.com
    port = int(os.getenv("PORT", 10000))

    if not token:
        logger.error("❌ Токен бота не найден в переменных окружения")
        return
    if not webhook_url:
        logger.error("❌ RENDER_EXTERNAL_URL не задан")
        return

    # Создаём приложение
    application = Application.builder().token(token).build()

    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setprice", set_price))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Полный URL вебхука
    webhook_path = "/webhook"
    webhook_full_url = f"{webhook_url}{webhook_path}"

    # Инициализация и запуск
    await application.initialize()
    await application.start()

    # Устанавливаем вебхук
    await application.bot.set_webhook(url=webhook_full_url)

    # Создаём веб-сервер
    app = web.Application()
    app['application'] = application
    
    # Регистрируем обработчики
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    app.router.add_post(webhook_path, webhook_handler)

    # Запускаем веб-сервер
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info(f"🌐 Бот запущен в режиме вебхука на порту {port}")
    logger.info(f"🔗 Webhook URL: {webhook_full_url}")

    # Обработка сигналов для корректного завершения
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    
    # Для Linux/MacOS
    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGTERM, stop_event.set)
        loop.add_signal_handler(signal.SIGINT, stop_event.set)
    # Для Windows
    else:
        def signal_handler(signum):
            stop_event.set()
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    # Ожидаем сигнал остановки
    await stop_event.wait()
    
    # Корректная остановка
    logger.info("Остановка бота...")
    await site.stop()
    await runner.cleanup()
    await application.stop()
    await application.shutdown()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
