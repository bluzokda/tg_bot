import os
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
import sqlite3
import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime

# Настройка логов
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Импортируем категории из categories.py
try:
    from categories import CATEGORIES
except ImportError:
    logger.error("Не удалось импортировать CATEGORIES из categories.py")
    # Определяем базовые категории на случай ошибки
    CATEGORIES = {
        3192: {"id": 3192, "name": "Ноутбуки и компьютеры", "url": "elektronika/noutbuki-pereferiya"},
        3281: {"id": 3281, "name": "Смартфоны и гаджеты", "url": "elektronika/smartfony-i-gadzhety"},
        617: {"id": 617, "name": "Телевизоры", "url": "elektronika/televizory"},
        813: {"id": 813, "name": "Красота и здоровье", "url": "krasota-i-zdorove"},
        1680: {"id": 1680, "name": "Дом и сад", "url": "dom-i-dacha"},
        907: {"id": 907, "name": "Одежда", "url": "zhenshchinam/odezhda"},
        908: {"id": 908, "name": "Обувь", "url": "zhenshchinam/obuv"},
    }

# Путь к базе данных
DB_PATH = 'user_data/users.db'

# Создаем базу данных, если она не существует
def init_db():
    os.makedirs('user_data', exist_ok=True)  # Создаем папку, если её нет
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            category_id INTEGER,
            price_threshold REAL,
            last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# Добавляем пользователя в базу данных
def add_user(user_id, category_id, price_threshold):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, category_id, price_threshold)
        VALUES (?, ?, ?)
    ''', (user_id, category_id, price_threshold))
    conn.commit()
    conn.close()

# Получаем данные пользователя из базы данных
def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, category_id, price_threshold FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

# Обновляем время последней проверки
def update_last_checked(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET last_checked = CURRENT_TIMESTAMP WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

# Парсим страницу категории на Wildberries
def parse_category(category_url):
    url = f"https://www.wildberries.ru/{category_url}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        products = []
        
        # Wildberries использует разные классы, пробуем основные
        product_cards = soup.find_all('div', class_='product-card')
        
        for card in product_cards:
            try:
                # Название товара
                name_tag = card.find('span', class_='goods-name')
                if not name_tag:
                    name_tag = card.find('span', class_='product-name')
                title = name_tag.get_text(strip=True) if name_tag else "Без названия"
                
                # Цена (ищем в разных возможных местах)
                price_tag = None
                # Основная цена (новая)
                price_tag = card.find('ins', class_='price')
                if not price_tag:
                    # Старая цена (если нет скидки)
                    price_tag = card.find('span', class_='price')
                if not price_tag:
                    # Цена в другом блоке
                    price_tag = card.find('span', class_='price-value')
                
                if price_tag:
                    # Удаляем все символы, кроме цифр и запятой/точки
                    price_text = price_tag.get_text(strip=True)
                    price_clean = ''.join(c for c in price_text if c.isdigit() or c in ',.')
                    price_clean = price_clean.replace(',', '.')
                    price = float(price_clean) if price_clean else 0
                else:
                    price = 0
                
                # Ссылка на товар
                link_tag = card.find('a')
                if link_tag and 'href' in link_tag.attrs:
                    link = link_tag['href']
                    if link.startswith('/'):
                        link = f"https://www.wildberries.ru{link}"
                    else:
                        link = f"https://www.wildberries.ru/{link}"
                else:
                    link = "#"
                
                if price > 0:
                    products.append({
                        'title': title,
                        'price': price,
                        'link': link
                    })
                    
            except Exception as e:
                logger.error(f"Ошибка при парсинге карточки товара: {e}")
                continue
        
        logger.info(f"Найдено {len(products)} товаров в категории {category_url}")
        return products
        
    except Exception as e:
        logger.error(f"Не удалось получить страницу категории {url}: {e}")
        return []

# Проверяем цены товаров (асинхронная версия)
async def check_prices(context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, category_id, price_threshold FROM users')
    users = cursor.fetchall()
    conn.close()

    for user in users:
        user_id, category_id, price_threshold = user
        category = CATEGORIES.get(category_id)
        
        if category:
            products = parse_category(category['url'])
            found = 0
            
            for product in products:
                if product['price'] <= price_threshold:
                    message = (
                        f"🔥 <b>Найден товар по вашему запросу!</b>\n\n"
                        f"🏷️ <b>Название:</b> {product['title']}\n"
                        f"💰 <b>Цена:</b> {product['price']:,.0f} ₽\n"
                        f"🔗 <b>Ссылка:</b> <a href='{product['link']}'>Перейти</a>"
                    )
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=message,
                            parse_mode='HTML',
                            disable_web_page_preview=False
                        )
                        found += 1
                    except Exception as e:
                        logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
            
            if found > 0:
                update_last_checked(user_id)
                logger.info(f"Отправлено {found} уведомлений пользователю {user_id} по категории {category_id}")

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Привет! Я помогу вам отслеживать цены на Wildberries.\n\n"
        "Используйте команды:\n"
        "🔹 /set_category — выбрать категорию товаров\n"
        "🔹 /set_price — установить порог цены\n\n"
        "Я буду присылать уведомления, когда товары появятся по цене ниже вашей!"
    )

# Команда /set_category
async def set_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    categories_list = "\n".join([f"<b>{cat['id']}</b>. {cat['name']}" for cat in CATEGORIES.values()])
    await update.message.reply_text(
        "📋 Выберите категорию товаров:\n\n"
        f"{categories_list}\n\n"
        "Введите <b>номер</b> категории:",
        parse_mode='HTML'
    )
    context.user_data['state'] = 'set_category'

# Обработка выбора категории
async def process_set_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_input = update.message.text.strip()
    try:
        category_id = int(user_input)
        if category_id in CATEGORIES:
            context.user_data['category_id'] = category_id
            await update.message.reply_text(
                f"✅ Вы выбрали категорию: <b>{CATEGORIES[category_id]['name']}</b>\n\n"
                "Теперь установите порог цены с помощью команды /set_price.",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text("❌ Неверный номер категории. Попробуйте снова.")
    except ValueError:
        await update.message.reply_text("❌ Введите корректный номер категории (целое число).")

# Команда /set_price
async def set_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "💸 Введите максимальную цену (например, <b>15000</b>):",
        parse_mode='HTML'
    )
    context.user_data['state'] = 'set_price'

# Обработка установки порога цены
async def process_set_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_input = update.message.text.strip()
    try:
        price_threshold = float(user_input)
        if price_threshold <= 0:
            await update.message.reply_text("❌ Цена должна быть больше 0.")
            return
            
        if 'category_id' in context.user_data:
            category_id = context.user_data['category_id']
            user_id = update.effective_user.id
            
            add_user(user_id, category_id, price_threshold)
            
            await update.message.reply_text(
                f"✅ <b>Настройки сохранены!</b>\n\n"
                f"🔍 Категория: {CATEGORIES[category_id]['name']}\n"
                f"💰 Порог цены: {price_threshold:,.0f} ₽\n\n"
                "Я буду уведомлять вас о товарах по этой цене или ниже.",
                parse_mode='HTML'
            )
            # Очищаем состояние
            if 'state' in context.user_data:
                del context.user_data['state']
            if 'category_id' in context.user_data:
                del context.user_data['category_id']
                
        else:
            await update.message.reply_text(
                "❌ Сначала выберите категорию с помощью команды /set_category."
            )
    except ValueError:
        await update.message.reply_text("❌ Введите корректное значение цены (например, 10000.50).")

# Обработка текстовых сообщений
async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if 'state' in context.user_data:
        state = context.user_data['state']
        if state == 'set_category':
            await process_set_category(update, context)
        elif state == 'set_price':
            await process_set_price(update, context)
        # Состояние очищается в процессе обработки

# Главная функция
def main() -> None:
    # Инициализируем базу данных
    init_db()

    # Получаем токен из переменных окружения
    TOKEN = os.getenv('TOKEN')
    if not TOKEN:
        logger.error("Токен не найден! Установите переменную окружения TOKEN.")
        return

    # Создаем приложение (новый способ для v20+)
    application = Application.builder().token(TOKEN).build()

    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("set_category", set_category))
    application.add_handler(CommandHandler("set_price", set_price))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_message))

    # Создаем и запускаем планировщик
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_prices,
        'interval',
        minutes=60,
        args=[application],
        id='price_check_job'
    )
    scheduler.start()
    logger.info("Планировщик задач запущен (каждые 60 минут)")

    # Запускаем бота
    # Для локального запуска используем polling
    application.run_polling(allowed_updates=Update.ALL_TYPES)

    # Для хостинга (Render, Heroku) используйте вебхук:
    # PORT = int(os.environ.get('PORT', 8443))
    # application.run_webhook(
    #     listen="0.0.0.0",
    #     port=PORT,
    #     webhook_url=f"https://your-render-app-name.onrender.com/{TOKEN}"
    # )

if __name__ == '__main__':
    main()
