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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import time

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
    CATEGORIES = {}

# Путь к базе данных
DB_PATH = 'user_data/users.db'

# Создаем базу данных, если она не существует
def init_db():
    """Инициализация базы данных с обработкой возможных ошибок создания папки"""
    try:
        if not os.path.exists('user_data'):
            os.makedirs('user_data', exist_ok=True)
            logger.info("Папка user_data создана")
        else:
            logger.info("Папка user_data уже существует")
    except Exception as e:
        logger.warning(f"Не удалось создать папку user_data (возможно, уже существует): {e}")

    # Теперь подключаемся к базе данных
    try:
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
        logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка при создании таблицы в базе данных: {e}")

# Добавляем пользователя в базу данных
def add_user(user_id, category_id, price_threshold):
    """Добавление или обновление настроек пользователя"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO users 
        (user_id, category_id, price_threshold, last_checked)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    ''', (user_id, category_id, price_threshold))
    conn.commit()
    conn.close()

# Получаем данные пользователя из базы данных
def get_user(user_id):
    """Получение настроек пользователя"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, category_id, price_threshold 
        FROM users WHERE user_id = ?
    ''', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

# Обновляем время последней проверки
def update_last_checked(user_id):
    """Обновление времени последней проверки"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users SET last_checked = CURRENT_TIMESTAMP 
        WHERE user_id = ?
    ''', (user_id,))
    conn.commit()
    conn.close()

# Получаем товары из категории через API Wildberries
def parse_category(category_data):
    """
    Получает товары из категории через API Wildberries
    category_data: словарь с информацией о категории
    """
    try:
        if not category_data or 'url' not in category_data:
            return []
            
        # Формируем URL для API
        base_url = "https://catalog.wb.ru/catalog"
        category_url = category_data['url']
        query_param = category_data.get('query', 'subject')
        
        # Параметры запроса
        params = {
            'appType': '1',
            'curr': 'rub',
            'dest': '-1257786',  # Россия
            'lang': 'ru',
            'locale': 'ru',
            'page': '1',        # Первая страница
            'sort': 'popular',  # Сортировка по популярности
            'spp': '0',         # Кол-во показов
            query_param: category_data.get('id', '')
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json',
            'Referer': 'https://www.wildberries.ru/'
        }
        
        # Полный URL
        api_url = f"{base_url}/{category_url}/catalog"
        
        response = requests.get(
            api_url, 
            params=params, 
            headers=headers, 
            timeout=15
        )
        
        if response.status_code != 200:
            logger.error(f"API вернул статус {response.status_code}: {response.text}")
            return []
            
        data = response.json()
        products = []
        
        # Извлекаем список товаров
        products_data = data.get('data', {}).get('products', [])
        
        for item in products_data:
            try:
                # Основная цена (с учетом скидки)
                price = item.get('salePriceU', 0) / 100  # Цена в копейках -> рубли
                
                # Если цена 0, используем обычную цену
                if price == 0:
                    price = item.get('priceU', 0) / 100
                    
                # Название товара
                title = item.get('name', 'Без названия')
                
                # Артикул товара
                product_id = item.get('id')
                link = f"https://www.wildberries.ru/catalog/{product_id}/detail.aspx"
                
                if price > 0:
                    products.append({
                        'title': title,
                        'price': price,
                        'link': link
                    })
            except Exception as e:
                logger.error(f"Ошибка при обработке товара: {e}")
                continue
        
        logger.info(f"Получено {len(products)} товаров из API для {category_data.get('name', 'неизвестная категория')}")
        return products
        
    except Exception as e:
        logger.error(f"Не удалось получить товары через API: {e}")
        return []

# Проверяем цены товаров (асинхронная версия)
async def check_prices(context: ContextTypes.DEFAULT_TYPE):
    """Проверка цен для всех пользователей"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, category_id, price_threshold FROM users')
        users = cursor.fetchall()
        conn.close()
        
        if not users:
            logger.info("Нет пользователей для проверки")
            return
            
        for user in users:
            user_id, category_id, price_threshold = user
            category = CATEGORIES.get(category_id)
            
            if category:
                logger.info(f"Проверка категории {category['name']} для пользователя {user_id}")
                
                products = parse_category(category)
                found = 0
                
                for product in products:
                    if product['price'] <= price_threshold:
                        message = (
                            f"🔥 <b>Найден товар по вашему запросу!</b>\n\n"
                            f"🏷️ <b>Название:</b> {product['title']}\n"
                            f"💰 <b>Цена:</b> {product['price']:,.0f} ₽\n"
                            f"🔗 <b>Ссылка:</b> <a href='{product['link']}'>Перейти к товару</a>"
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
                    logger.info(f"Отправлено {found} уведомлений пользователю {user_id}")
                    
                # Задержка между проверками категорий
                time.sleep(2)
                
    except Exception as e:
        logger.error(f"Ошибка при проверке цен: {e}")

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    await update.message.reply_text(
        "👋 Привет! Я помогу вам отслеживать цены на Wildberries.\n\n"
        "Используйте команды:\n"
        "🔹 /set_category — выбрать категорию товаров\n"
        "🔹 /set_price — установить порог цены\n\n"
        "Я буду присылать уведомления, когда товары появятся по цене ниже вашей!"
    )

# Команда /set_category
async def set_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /set_category"""
    if not CATEGORIES:
        await update.message.reply_text("❌ Не удалось загрузить категории. Попробуйте позже.")
        return
        
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
    """Обработка ввода номера категории"""
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
    """Обработчик команды /set_price"""
    if 'category_id' not in context.user_data:
        await update.message.reply_text(
            "❌ Сначала выберите категорию с помощью команды /set_category."
        )
        return
        
    await update.message.reply_text(
        "💸 Введите максимальную цену (например, <b>15000</b>):",
        parse_mode='HTML'
    )
    context.user_data['state'] = 'set_price'

# Обработка установки порога цены
async def process_set_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка ввода порога цены"""
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
    """Обработка текстовых сообщений"""
    if 'state' in context.user_data:
        state = context.user_data['state']
        if state == 'set_category':
            await process_set_category(update, context)
        elif state == 'set_price':
            await process_set_price(update, context)

# Главная функция
def main() -> None:
    """Главная функция запуска бота"""
    # Инициализируем базу данных
    init_db()

    # Получаем токен из переменных окружения
    TOKEN = os.getenv('TOKEN')
    if not TOKEN:
        logger.error("Токен не найден! Установите переменную окружения TOKEN.")
        return

    # Создаем приложение
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
    logger.info("Запуск бота...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
