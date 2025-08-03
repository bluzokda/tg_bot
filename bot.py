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

def get_catalogs_wb() -> dict:
    url = 'https://static-basket-01.wbbasket.ru/vol0/data/main-menu-ru-ru-v3.json'
    headers = {'Accept': '*/*', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    return requests.get(url, headers=headers).json()

def get_data_category(catalogs_wb: dict) -> list:
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
    for catalog in catalog_list:
        if catalog['url'] == url.split('https://www.wildberries.ru')[-1]:
            return catalog

def get_data_from_json(json_file: dict) -> list:
    data_list = []
    for data in json_file['data']['products']:
        data_list.append({
            'id': data.get('id'),
            'name': data.get('name'),
            'price': int(data.get("priceU", 0) / 100,
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
    df = pd.DataFrame(data)
    filename = f"{filename.replace('/', '_').replace(':', '')}.xlsx"
    df.to_excel(filename, index=False)
    return filename

def parser(url: str, low_price: int = 1, top_price: int = 1000000, discount: int = 0):
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
            
            if 'data' not in data or 'products' not in data['data']:
                break
                
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я парсер Wildberries.\n"
        "Используй команду:\n"
        "/parse [ссылка] [мин.цена] [макс.цена] [скидка]\n\n"
        "Пример:\n"
        "/parse https://www.wildberries.ru/catalog/elektronika/planshety 10000 15000 10"
    )

async def parse_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = context.args
        if len(args) < 4:
            await update.message.reply_text("Формат команды:\n"
                                           "/parse [ссылка] [мин.цена] [макс.цена] [скидка]")
            return

        url = args[0]
        low_price = int(args[1])
        top_price = int(args[2])
        discount = int(args[3])
        
        await update.message.reply_text("⏳ Парсинг начат...")
        
        filename, message = parser(url, low_price, top_price, discount)
        
        if filename:
            await update.message.reply_document(
                document=open(filename, 'rb'),
                caption=f"✅ {message}\n"
                       f"Ссылка: {url}\n"
                       f"Цены: {low_price}-{top_price} руб\n"
                       f"Скидка: {discount}%"
            )
            os.remove(filename)
        else:
            await update.message.reply_text(f"❌ {message}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка: {str(e)}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 Помощь:\n\n"
        "Формат команды:\n"
        "/parse [ссылка] [мин.цена] [макс.цена] [скидка]\n\n"
        "Пример:\n"
        "/parse https://www.wildberries.ru/catalog/elektronika/planshety 5000 20000 15\n\n"
        "Ссылка должна быть без фильтров!"
    )

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("Не задан TELEGRAM_BOT_TOKEN")
    
    application = Application.builder().token(token).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("parse", parse_command))
    application.add_handler(CommandHandler("help", help_command))
    
    print("Бот запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()
