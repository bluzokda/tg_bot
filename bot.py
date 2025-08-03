from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext
import json
import os
from categories import CATEGORIES
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
import requests

# Путь к папке с данными пользователей
USER_DATA_DIR = "user_data"

# Создаем директорию для хранения данных пользователей, если она не существует
if not os.path.exists(USER_DATA_DIR):
    os.makedirs(USER_DATA_DIR)

def start(update: Update, context: CallbackContext):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    user_data_file = os.path.join(USER_DATA_DIR, f"{user_id}.json")
    
    # Проверяем, есть ли уже данные пользователя
    if os.path.exists(user_data_file):
        with open(user_data_file, "r") as f:
            user_data = json.load(f)
    else:
        user_data = {}
    
    # Отправляем приветственное сообщение
    update.message.reply_text(
        "Привет! Я помогу тебе отслеживать цены на Wildberries.\n"
        "Выбери категорию, которую ты хочешь отслеживать:",
        reply_markup=get_category_keyboard()
    )

def get_category_keyboard():
    """Возвращает клавиатуру с категориями"""
    keyboard = []
    for category in CATEGORIES.values():
        button = InlineKeyboardButton(category['name'], callback_data=f"category_{category['id']}")
        keyboard.append([button])
    return InlineKeyboardMarkup(keyboard)

def category_callback(update: Update, context: CallbackContext):
    """Обработчик выбора категории"""
    query = update.callback_query
    category_id = int(query.data.split("_")[1])
    category = CATEGORIES[category_id]
    
    # Сохраняем выбранную категорию
    user_id = update.effective_user.id
    user_data_file = os.path.join(USER_DATA_DIR, f"{user_id}.json")
    
    user_data = {}
    if os.path.exists(user_data_file):
        with open(user_data_file, "r") as f:
            user_data = json.load(f)
    
    user_data['category_id'] = category_id
    user_data['category_name'] = category['name']
    
    with open(user_data_file, "w") as f:
        json.dump(user_data, f)
    
    # Запрашиваем максимальную цену
    query.edit_message_text(
        f"Вы выбрали категорию: {category['name']}\n"
        "Введите максимальную цену, ниже которой нужно уведомлять вас:"
    )
    return "waiting_for_price"

def waiting_for_price(update: Update, context: CallbackContext):
    """Обработчик ввода максимальной цены"""
    user_id = update.effective_user.id
    max_price = update.message.text
    
    try:
        max_price = float(max_price)
    except ValueError:
        update.message.reply_text("Пожалуйста, введите корректную цену.")
        return "waiting_for_price"
    
    # Сохраняем максимальную цену
    user_data_file = os.path.join(USER_DATA_DIR, f"{user_id}.json")
    with open(user_data_file, "r") as f:
        user_data = json.load(f)
    
    user_data['max_price'] = max_price
    
    with open(user_data_file, "w") as f:
        json.dump(user_data, f)
    
    update.message.reply_text(
        f"Настройки сохранены:\n"
        f"Категория: {user_data['category_name']}\n"
        f"Максимальная цена: {max_price}\n"
        "Я буду следить за изменениями цен!"
    )

def check_prices():
    """Проверяет цены товаров в выбранных категориях"""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    bot = Bot(token=bot_token)
    
    for user_data_file in os.listdir(USER_DATA_DIR):
        user_id = int(user_data_file.split(".")[0])
        with open(os.path.join(USER_DATA_DIR, user_data_file), "r") as f:
            user_data = json.load(f)
        
        category_id = user_data.get('category_id')
        max_price = user_data.get('max_price')
        category = CATEGORIES.get(category_id)
        
        if category and max_price:
            url = f"https://www.wildberries.ru{category['url']}?{category['query']}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                products = soup.find_all('div', class_='product-card')
                
                for product in products:
                    price_element = product.find('ins', class_='price')
                    name_element = product.find('span', class_='goods-name')
                    
                    if price_element and name_element:
                        price = float(price_element.text.replace(' ', '').replace('₽', ''))
                        name = name_element.text.strip()
                        
                        if price <= max_price:
                            send_notification(bot, user_id, name, price)

def send_notification(bot: Bot, user_id: int, product_name: str, price: float):
    """Отправляет уведомление пользователю"""
    message = (
        f"🚨 Найден товар по вашему запросу:\n"
        f"Название: {product_name}\n"
        f"Цена: {price} ₽\n"
        f"Ссылка: https://www.wildberries.ru/catalog/{CATEGORIES[user_id]['url']}"
    )
    bot.send_message(chat_id=user_id, text=message)

def main():
    """Основная функция для запуска бота"""
    # Получаем токен из переменных окружения
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    # Создаем updater и dispatcher
    updater = Updater(token, use_context=True)
    dp = updater.dispatcher
    
    # Регистрируем обработчики команд
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(category_callback))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, waiting_for_price))
    
    # Запускаем планировщик задач
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_prices, 'interval', minutes=10)  # Проверка каждые 10 минут
    scheduler.start()
    
    # Запускаем бота
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
