import os
import logging
import requests
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
        "2. Затем отправь мне название товара или категории для поиска"
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
            await update.message.reply_text("😢 Товары не найдены. Попробуйте другое название.")
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
    Поиск товаров на Wildberries через публичный API.
    Использует catalog.wb.ru — не требует JS, обходит базовую защиту.
    """
    url = "https://catalog.wb.ru/search/catalog"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.wildberries.ru/",
        "Origin": "https://www.wildberries.ru",
        "Connection": "keep-alive"
    }

    params = {
        "appType": 1,
        "curr": "rub",
        "dest": -1257786,           # Россия
        "lang": "ru",
        "locale": "ru",
        "page": 1,
        "query": query.strip(),
        "resultset": "catalog",
        "sort": "popular",
        "spp": 30,                  # Кол-во показов на странице
        "suppressSpellcheck": False
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        
        # Логируем статус и начало тела ответа
        logger.info(f"Wildberries API: {response.status_code} для запроса '{query}'")
        
        if response.status_code != 200:
            logger.error(f"Ошибка API: статус {response.status_code}, тело: {response.text[:300]}")
            return []

        # Проверка на антибот (если в ответе HTML вместо JSON)
        if not response.text.startswith("{"):
            logger.warning("Получен HTML — возможно, сработал антибот")
            if "JavaScript" in response.text or "проверки браузера" in response.text:
                logger.error("🚫 Антибот Wildberries заблокировал запрос!")
            return []

        data = response.json()

        # Проверка структуры ответа
        products_data = data.get("data", {}).get("products", [])
        if not products_data:
            logger.info(f"Нет товаров по запросу '{query}'")
            return []

        products = []
        for item in products_data[:20]:  # Берём максимум 20
            # Основная цена и скидка
            price_u = item.get("priceU")  # обычная цена в копейках
            sale_price_u = item.get("salePriceU") or price_u
            if not sale_price_u:
                continue

            # Формируем данные
            product = {
                "name": item.get("name", "Без названия").strip(),
                "price": sale_price_u // 100,  # в рублях
                "rating": float(item.get("reviewRating", 0)),
                "feedbacks": int(item.get("feedbacks", 0)),
                "link": f"https://www.wildberries.ru/catalog/{item['id']}/detail.aspx"
            }
            products.append(product)

        logger.info(f"Найдено {len(products)} товаров по запросу '{query}'")
        return products

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка сети при запросе к Wildberries: {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка при парсинге: {e}", exc_info=True)

    return []


def main() -> None:
    """Основная функция запуска бота"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("❌ Токен бота не найден в переменных окружения")
        return

    # Создаем приложение
    application = Application.builder().token(token).build()

    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setprice", set_price))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Запуск бота
    logger.info("🚀 Бот запущен и готов к работе")
    application.run_polling()


if __name__ == "__main__":
    main()
