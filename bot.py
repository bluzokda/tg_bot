from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import json
import os
from categories import CATEGORIES
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import aiohttp
import asyncio
from bs4 import BeautifulSoup
import sys  # Для диагностики

# Диагностика версий
print("=== SYSTEM INFORMATION ===")
print(f"Python version: {sys.version}")
print(f"Current working directory: {os.getcwd()}")
print("Directory contents:", os.listdir())
print("==========================")

# Путь к папке с данными пользователей
USER_DATA_DIR = "user_data"

# Создаем директорию, если её нет
if not os.path.exists(USER_DATA_DIR):
    os.makedirs(USER_DATA_DIR)

# === ОБРАБОТЧИКИ КОМАНД ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /start"""
    user_id = update.effective_user.id
    user_data_file = os.path.join(USER_DATA_DIR, f"{user_id}.json")

    # Загружаем данные пользователя
    if os.path.exists(user_data_file):
        with open(user_data_file, "r", encoding="utf-8") as f:
            user_data = json.load(f)
    else:
        user_data = {}

    # Сохраняем в контекст ожидание выбора категории
    context.user_data['state'] = 'awaiting_category'

    # Отправляем сообщение с выбором категории
    await update.message.reply_text(
        "Привет! Я помогу тебе отслеживать цены на Wildberries.\n"
        "Выбери категорию:",
        reply_markup=get_category_keyboard()
    )

def get_category_keyboard():
    """Генерация клавиатуры с категориями"""
    keyboard = []
    for category in CATEGORIES.values():
        button = InlineKeyboardButton(category['name'], callback_data=f"cat_{category['id']}")
        keyboard.append([button])
    return InlineKeyboardMarkup(keyboard)

async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора категории"""
    query = update.callback_query
    await query.answer()

    category_id = int(query.data.split("_")[1])
    category = CATEGORIES.get(category_id)

    if not category:
        await query.edit_message_text("Ошибка: категория не найдена.")
        return

    # Сохраняем категорию
    user_id = update.effective_user.id
    user_data_file = os.path.join(USER_DATA_DIR, f"{user_id}.json")

    user_data = {}
    if os.path.exists(user_data_file):
        with open(user_data_file, "r", encoding="utf-8") as f:
            user_data = json.load(f)

    user_data['category_id'] = category_id
    user_data['category_name'] = category['name']

    with open(user_data_file, "w", encoding="utf-8") as f:
        json.dump(user_data, f, ensure_ascii=False, indent=2)

    # Запрашиваем цену
    context.user_data['state'] = 'awaiting_price'
    await query.edit_message_text(
        f"✅ Выбрана категория: *{category['name']}*\n"
        "Введите максимальную цену (в рублях):",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений (ввод цены)"""
    user_id = update.effective_user.id
    user_data_file = os.path.join(USER_DATA_DIR, f"{user_id}.json")

    state = context.user_data.get('state')

    if state == 'awaiting_price':
        try:
            max_price = float(update.message.text)
            if max_price <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("Введите корректное число больше 0.")
            return

        # Загружаем и обновляем данные
        user_data = {}
        if os.path.exists(user_data_file):
            with open(user_data_file, "r", encoding="utf-8") as f:
                user_data = json.load(f)

        user_data['max_price'] = max_price

        with open(user_data_file, "w", encoding="utf-8") as f:
            json.dump(user_data, f, ensure_ascii=False, indent=2)

        await update.message.reply_text(
            f"🎯 Отлично! Я буду присылать уведомления, если цена упадёт ниже *{max_price} ₽*.\n"
            "Я буду проверять каждые 10 минут.",
            parse_mode="Markdown"
        )
        context.user_data['state'] = None


# === ПРОВЕРКА ЦЕН ===

async def check_prices():
    """Асинхронная проверка цен"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Ошибка: TELEGRAM_BOT_TOKEN не установлен")
        return

    bot = Bot(token=token)

    for filename in os.listdir(USER_DATA_DIR):
        if not filename.endswith(".json"):
            continue
            
        user_id = int(filename.split(".")[0])
        user_data_file = os.path.join(USER_DATA_DIR, filename)

        try:
            with open(user_data_file, "r", encoding="utf-8") as f:
                user_data = json.load(f)

            category_id = user_data.get('category_id')
            max_price = user_data.get('max_price')
            category = CATEGORIES.get(category_id)

            if not category or not max_price:
                print(f"Пропускаем пользователя {user_id}: отсутствуют данные о категории или цене")
                continue

            # Формируем URL
            base_url = "https://www.wildberries.ru"
            url = f"{base_url}{category['url']}?{category['query']}"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3"
            }

            print(f"Проверяем цены для пользователя {user_id} в категории {category['name']}...")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=15) as response:
                    if response.status != 200:
                        print(f"Не удалось загрузить {url} (статус {response.status})")
                        continue
                    
                    html = await response.text()
                    soup = BeautifulSoup(html, "html.parser")
                    
                    # Селекторы для Wildberries
                    products = soup.find_all("article", class_="product-card")
                    
                    notified = False
                    for product in products[:10]:
                        # Цена
                        price_tag = product.find("ins", class_="price__lower-price") or product.find("span", class_="price__lower-price")
                        if not price_tag:
                            continue
                            
                        # Название
                        name_tag = product.find("span", class_="product-card__name")
                        # Ссылка
                        link_tag = product.find("a", class_="product-card__link")
                        
                        if not name_tag or not link_tag:
                            continue
                            
                        try:
                            # Обработка цены
                            price_text = price_tag.get_text(strip=True)
                            price_text = price_text.replace(" ", "").replace("₽", "").replace("\xa0", "").split("₽")[0]
                            price = float(price_text)
                            
                            name = name_tag.get_text(strip=True)
                            product_url = base_url + link_tag["href"]
                        except Exception as e:
                            print(f"Ошибка парсинга товара: {e}")
                            continue
                            
                        print(f"Товар: {name} | Цена: {price} | Макс. цена: {max_price}")
                            
                        if price <= max_price:
                            try:
                                await bot.send_message(
                                    chat_id=user_id,
                                    text=f"🔥 *Цена упала!* \n"
                                         f"📦 {name}\n"
                                         f"💰 {price} ₽\n"
                                         f"🔗 [Смотреть товар]({product_url})",
                                    parse_mode="Markdown",
                                    disable_web_page_preview=False
                                )
                                print(f"Отправлено уведомление пользователю {user_id}")
                            except Exception as e:
                                print(f"Ошибка отправки сообщения пользователю {user_id}: {e}")
                            notified = True
                            break
                            
            if not notified:
                print(f"Для пользователя {user_id} нет подходящих товаров.")
        except Exception as e:
            print(f"Ошибка при обработке пользователя {filename}: {e}")


# === ЗАПУСК БОТА ===

def main():
    """Главная функция"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не установлен в переменных окружения!")

    # Создаём приложение
    application = Application.builder().token(token).build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(category_callback, pattern="^cat_\\d+"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запускаем планировщик
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_prices, "interval", minutes=10)
    scheduler.start()

    # Запускаем бота
    print("Бот запущен. Ожидаем команд...")
    application.run_polling()

if __name__ == "__main__":
    main()
