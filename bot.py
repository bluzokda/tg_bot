import os
import logging
import requests
import time
import re
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
        await update.message.reply_text(f"✅ Установлена целевая цена: {price} руб.\nТеперь отправь название товара для поиска.")
        
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
            await update.message.reply_text("😢 Товары не найдены. Попробуйте другой запрос.")
            return
            
        # Фильтрация и сортировка результатов
        filtered_products = [
            p for p in products 
            if p["price"] <= target_price
        ]
        filtered_products.sort(key=lambda x: x["price"])
        
        if not filtered_products:
            await update.message.reply_text(f"😢 Нет товаров ниже {target_price} руб. Попробуйте увеличить цену.")
            return
            
        # Формирование сообщения с результатами
        message = f"✅ Найдено {len(filtered_products)} товаров по вашим критериям:\n\n"
        for i, product in enumerate(filtered_products[:5], 1):
            # Очистка названия от HTML-тегов
            clean_name = re.sub(r'<[^>]+>', '', product['name'])
            
            message += (
                f"{i}. {clean_name}\n"
                f"💵 Цена: {product['price']} руб. "
                f"({product['discount']}% скидка)\n"
                f"⭐ Рейтинг: {product['rating']} | ✨ Отзывов: {product['feedbacks']}\n"
                f"🛒 [Купить]({product['link']})\n\n"
            )
        
        await update.message.reply_text(
            message, 
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Ошибка при поиске товаров: {e}", exc_info=True)
        await update.message.reply_text("⚠ Произошла ошибка при обработке запроса")

def search_wildberries(query: str) -> list:
    """Поиск товаров на Wildberries через API (обновленная версия)"""
    # Генерация уникального URL для каждого запроса
    timestamp = int(time.time() * 1000)
    url = f"https://search.wb.ru/exactmatch/ru/common/v4/search?TestGroup=search_2&TestID=367&appType=1&curr=rub&dest=-1257786&query={query}&resultset=catalog&sort=popular&spp=30&suppressSpellcheck=false&uclusters=1&{timestamp}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
        "Referer": f"https://www.wildberries.ru/catalog/0/search.aspx?page=1&sort=popular&search={query}",
        "Origin": "https://www.wildberries.ru",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        products = []
        
        # Проверка наличия данных
        if "data" not in data or "products" not in data["data"]:
            logger.warning(f"Нет данных в ответе API. Ответ: {data}")
            return products
        
        # Обработка товаров
        for item in data["data"]["products"]:
            # Проверка наличия цены
            if "salePriceU" not in item:
                continue
                
            # Получение данных
            price = item["salePriceU"] // 100
            original_price = item.get("priceU", price * 100) // 100
            discount = 0
            
            # Расчет скидки
            if original_price > price:
                discount = int((1 - price / original_price) * 100)
            
            # Формирование информации о товаре
            products.append({
                "name": item.get("name", "Без названия"),
                "price": price,
                "rating": item.get("reviewRating", 0),
                "feedbacks": item.get("feedbacks", 0),
                "discount": discount,
                "link": f"https://www.wildberries.ru/catalog/{item['id']}/detail.aspx"
            })
        
        logger.info(f"Найдено {len(products)} товаров для запроса '{query}'")
        return products
        
    except Exception as e:
        logger.error(f"Ошибка API Wildberries: {e}", exc_info=True)
        return []

def main() -> None:
    """Основная функция запуска бота"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("Токен бота не найден в переменных окружения")
        return
    
    # Создаем приложение
    application = Application.builder().token(token).build()
    
    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setprice", set_price))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Запускаем бота в режиме поллинга
    logger.info("🚀 Бот запущен в режиме поллинга")
    application.run_polling()

if __name__ == "__main__":
    main()
