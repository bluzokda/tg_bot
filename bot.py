from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import json
import os
from categories import CATEGORIES
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
import requests

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

def check_prices():
    """Фоновая проверка цен"""
    # Получаем токен
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Ошибка: TELEGRAM_BOT_TOKEN не установлен")
        return

    from telegram import Bot

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
                continue

            # Формируем URL для поиска
            base_url = "https://www.wildberries.ru"
            url = f"{base_url}{category['url']}?{category['query']}"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }

            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            products = soup.find_all("div", class_="product-card")

            notified = False
            for product in products[:10]:  # Проверяем первые 10 товаров
                price_tag = product.find("ins", class_="price")
                name_tag = product.find("span", class_="goods-name")

                if not price_tag or not name_tag:
                    continue

                try:
                    price_text = price_tag.get_text(strip=True).replace(" ", "").replace("₽", "")
                    price = float(price_text)
                    name = name_tag.get_text(strip=True)
                except:
                    continue

                if price <= max_price:
                    link = product.find("a", href=True)
                    product_url = base_url + link["href"] if link else base_url

                    await bot.send_message(
                        chat_id=user_id,
                        text=f"🔥 *Цена упала!* \n"
                             f"📦 {name}\n"
                             f"💰 {price} ₽\n"
                             f"🔗 [Смотреть товар]({product_url})",
                        parse_mode="Markdown",
                        disable_web_page_preview=False
                    )
                    notified = True
                    break  # Одно уведомление на проверку — чтобы не спамить

            if not notified:
                print(f"Для пользователя {user_id} нет подходящих товаров.")
        except Exception as e:
            print(f"Ошибка при проверке для {user_id}: {e}")

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
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_prices, "interval", minutes=10)
    scheduler.start()

    # Запускаем бота
    print("Бот запущен. Ожидаем команд...")
    application.run_polling()

if __name__ == "__main__":
    main()
