import datetime
import requests
import json
import pandas as pd
from retry import retry
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)

"""
Парсер Wildberries для Telegram бота
"""

def get_catalogs_wb() -> dict:
    """получаем полный каталог Wildberries"""
    url = 'https://static-basket-01.wbbasket.ru/vol0/data/main-menu-ru-ru-v3.json'
    headers = {'Accept': '*/*', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    return requests.get(url, headers=headers).json()

def get_data_category(catalogs_wb: dict) -> list:
    """сбор данных категорий из каталога Wildberries"""
    catalog_data = []
    if isinstance(catalogs_wb, dict) and 'childs' not in catalogs_wb:
        catalog_data.append({
            'name': f"{catalogs_wb['name']}",
            'shard': catalogs_wb.get('shard', None),
            'url': catalogs_wb['url'],
            'query': catalogs_wb.get('query', None)
        })
    elif isinstance(catalogs_wb, dict):
        catalog_data.append({
            'name': f"{catalogs_wb['name']}",
            'shard': catalogs_wb.get('shard', None),
            'url': catalogs_wb['url'],
            'query': catalogs_wb.get('query', None)
        })
        catalog_data.extend(get_data_category(catalogs_wb['childs']))
    else:
        for child in catalogs_wb:
            catalog_data.extend(get_data_category(child))
    return catalog_data

def search_category_in_catalog(url: str, catalog_list: list) -> dict:
    """проверка пользовательской ссылки на наличии в каталоге"""
    for catalog in catalog_list:
        if catalog['url'] == url.split('https://www.wildberries.ru')[-1]:
            return catalog

def get_data_from_json(json_file: dict) -> list:
    """извлекаем из json данные"""
    data_list = []
    for data in json_file['data']['products']:
        data_list.append({
            'id': data.get('id'),
            'name': data.get('name'),
            'price': int(data.get("priceU", 0) / 100),
            'salePriceU': int(data.get('salePriceU', 0) / 100,
            'cashback': data.get('feedbackPoints'),
            'sale': data.get('sale'),
            'brand': data.get('brand'),
            'rating': data.get('rating'),
            'supplier': data.get('supplier'),
            'supplierRating': data.get('supplierRating'),
            'feedbacks': data.get('feedbacks'),
            'reviewRating': data.get('reviewRating'),
            'promoTextCard': data.get('promoTextCard'),
            'promoTextCat': data.get('promoTextCat'),
            'link': f'https://www.wildberries.ru/catalog/{data.get("id")}/detail.aspx?targetUrl=BP'
        })
    return data_list

@retry(Exception, tries=-1, delay=0)
def scrap_page(page: int, shard: str, query: str, low_price: int, top_price: int, discount: int = None) -> dict:
    """Сбор данных со страниц"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0)"}
    url = f'https://catalog.wb.ru/catalog/{shard}/catalog?appType=1&curr=rub' \
          f'&dest=-1257786' \
          f'&locale=ru' \
          f'&page={page}' \
          f'&priceU={low_price * 100};{top_price * 100}' \
          f'&sort=popular&spp=0' \
          f'&{query}' \
          f'&discount={discount}'
    r = requests.get(url, headers=headers)
    return r.json()

def save_excel(data: list, filename: str):
    """сохранение результата в excel файл"""
    df = pd.DataFrame(data)
    filename = f"{filename.replace('/', '_')}.xlsx"
    df.to_excel(filename, index=False)
    return filename

def parser(url: str, low_price: int = 1, top_price: int = 1000000, discount: int = 0):
    """основная функция парсинга"""
    catalog_data = get_data_category(get_catalogs_wb())
    try:
        category = search_category_in_catalog(url=url, catalog_list=catalog_data)
        if not category:
            return None, "Категория не найдена в каталоге Wildberries"
        
        data_list = []
        for page in range(1, 51):
            data = scrap_page(
                page=page,
                shard=category['shard'],
                query=category['query'],
                low_price=low_price,
                top_price=top_price,
                discount=discount)
            
            page_data = get_data_from_json(data)
            if not page_data:
                break
            data_list.extend(page_data)
        
        if not data_list:
            return None, "Товары не найдены по заданным параметрам"
        
        filename = save_excel(data_list, f"{category['name']}_{low_price}_{top_price}_{discount}")
        return filename, f"Собрано {len(data_list)} товаров"
    except Exception as e:
        return None, f"Ошибка: {str(e)}"

# ====== Telegram Bot Handlers ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /start"""
    await update.message.reply_text(
        "Привет! Я парсер Wildberries.\n"
        "Используй команду /parse с параметрами:\n"
        "/parse [ссылка] [мин.цена] [макс.цена] [скидка]\n\n"
        "Пример:\n"
        "/parse https://www.wildberries.ru/catalog/elektronika/planshety 10000 15000 10"
    )

async def parse_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /parse"""
    try:
        args = context.args
        if len(args) < 4:
            await update.message.reply_text("Недостаточно параметров. Формат:\n"
                                           "/parse [ссылка] [мин.цена] [макс.цена] [скидка]")
            return

        url = args[0]
        low_price = int(args[1])
        top_price = int(args[2])
        discount = int(args[3])
        
        # Уведомление о начале обработки
        await update.message.reply_text("⏳ Начинаю парсинг... Это может занять несколько минут")
        
        # Вызов парсера
        filename, message = parser(url, low_price, top_price, discount)
        
        if filename:
            # Отправка файла
            await update.message.reply_document(
                document=open(filename, 'rb'),
                caption=f"✅ {message}\n"
                       f"Ссылка: {url}\n"
                       f"Цены: {low_price}-{top_price} руб\n"
                       f"Скидка: {discount}%"
            )
            # Удаление временного файла
            os.remove(filename)
        else:
            await update.message.reply_text(f"❌ {message}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка: {str(e)}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /help"""
    await update.message.reply_text(
        "📚 Помощь по использованию бота:\n\n"
        "1. Найти нужную категорию на сайте Wildberries\n"
        "2. Скопировать URL без фильтров\n"
        "3. Использовать команду:\n"
        "/parse [ссылка] [мин.цена] [макс.цена] [скидка]\n\n"
        "Пример:\n"
        "/parse https://www.wildberries.ru/catalog/elektronika/planshety 5000 20000 15\n\n"
        "Бот соберет товары в указанном ценовом диапазоне с минимальной скидкой."
    )

def main():
    """Запуск бота"""
    # Получение токена из переменных окружения
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("Не задан TELEGRAM_BOT_TOKEN в переменных окружения")
    
    # Создание Application
    application = Application.builder().token(token).build()
    
    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("parse", parse_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # Запуск бота
    print("Бот запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()
