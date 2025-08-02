import os
import logging
from telegram import Update
from telegram.ext import (
    Updater, 
    CommandHandler, 
    MessageHandler, 
    Filters, 
    CallbackContext
)
import sqlite3
import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta

# Настройка логов
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Путь к базе данных
DB_PATH = 'user_data/users.db'

# Создаем базу данных, если она не существует
def init_db():
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
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
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
    response = requests.get(url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        products = []
        for product in soup.find_all('div', class_='product-card'):
            try:
                title = product.find('span', class_='goods-name').text.strip()
                price = float(product.find('ins', class_='price').text.replace(' ', '').replace('₽', ''))
                link = product.find('a')['href']
                products.append({
                    'title': title,
                    'price': price,
                    'link': f"https://www.wildberries.ru{link}"
                })
            except Exception as e:
                logger.error(f"Ошибка при парсинге продукта: {e}")
        return products
    else:
        logger.error(f"Не удалось получить страницу категории: {url}")
        return []

# Проверяем цены товаров
def check_prices(context: CallbackContext):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users')
    users = cursor.fetchall()
    conn.close()

    for user in users:
        user_id, category_id, price_threshold = user
        category = CATEGORIES.get(category_id)
        if category:
            products = parse_category(category['url'])
            for product in products:
                if product['price'] <= price_threshold:
                    message = (
                        f"Найден товар по вашему запросу:\n"
                        f"🏷️ Название: {product['title']}\n"
                        f"💰 Цена: {product['price']} ₽\n"
                        f"🔗 Ссылка: {product['link']}"
                    )
                    context.bot.send_message(chat_id=user_id, text=message)
            update_last_checked(user_id)

# Команда /start
def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        "Привет! Я помогу вам отслеживать цены на Wildberries.\n"
        "Используйте команду /set_category, чтобы выбрать категорию товаров.\n"
        "Используйте команду /set_price, чтобы установить порог цены."
    )

# Команда /set_category
def set_category(update: Update, context: CallbackContext) -> None:
    categories_list = "\n".join([f"{cat['id']}. {cat['name']}" for cat in CATEGORIES.values()])
    update.message.reply_text(
        "Выберите категорию товаров:\n"
        f"{categories_list}\n\n"
        "Введите номер категории:"
    )

    # Сохраняем состояние пользователя
    context.user_data['state'] = 'set_category'

# Обработка выбора категории
def process_set_category(update: Update, context: CallbackContext) -> None:
    user_input = update.message.text
    try:
        category_id = int(user_input)
        if category_id in CATEGORIES:
            context.user_data['category_id'] = category_id
            update.message.reply_text(
                f"Вы выбрали категорию: {CATEGORIES[category_id]['name']}\n"
                "Теперь установите порог цены с помощью команды /set_price."
            )
        else:
            update.message.reply_text("Неверный номер категории. Попробуйте снова.")
    except ValueError:
        update.message.reply_text("Введите корректный номер категории.")

# Команда /set_price
def set_price(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        "Введите порог цены (например, 10000):"
    )

    # Сохраняем состояние пользователя
    context.user_data['state'] = 'set_price'

# Обработка установки порога цены
def process_set_price(update: Update, context: CallbackContext) -> None:
    user_input = update.message.text
    try:
        price_threshold = float(user_input)
        if 'category_id' in context.user_data:
            category_id = context.user_data['category_id']
            add_user(update.effective_user.id, category_id, price_threshold)
            update.message.reply_text(
                f"Настроено отслеживание для категории: {CATEGORIES[category_id]['name']}\n"
                f"Порог цены: {price_threshold} ₽"
            )
        else:
            update.message.reply_text("Сначала выберите категорию с помощью команды /set_category.")
    except ValueError:
        update.message.reply_text("Введите корректное значение цены.")

# Запуск задачи на фоне
def start_scheduler(context: CallbackContext):
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_prices, 'interval', minutes=60, args=[context])
    scheduler.start()

# Главная функция
def main() -> None:
    # Инициализируем базу данных
    init_db()

    # Получаем токен из переменных окружения
    TOKEN = os.getenv('TOKEN')
    if not TOKEN:
        logger.error("Токен не найден! Установите переменную окружения TOKEN.")
        return

    # Создаем бота
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher

    # Регистрируем обработчики
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("set_category", set_category))
    dispatcher.add_handler(CommandHandler("set_price", set_price))

    # Обработка текстовых сообщений
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, process_message))

    # Запускаем планировщик задач
    start_scheduler(dispatcher)

    # Режим работы (для Render)
    PORT = int(os.environ.get('PORT', 10000))
    updater.start_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://your-render-app-name.onrender.com/{TOKEN}"
    )
    updater.idle()

# Обработка текстовых сообщений
def process_message(update: Update, context: CallbackContext) -> None:
    if 'state' in context.user_data:
        state = context.user_data['state']
        if state == 'set_category':
            process_set_category(update, context)
        elif state == 'set_price':
            process_set_price(update, context)
        del context.user_data['state']

if __name__ == '__main__':
    main()
