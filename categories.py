import requests

def fetch_categories():
    """Получаем категории с WB API"""
    try:
        # Основной URL для получения меню
        url = "https://static-basket-01.wbbasket.ru/vol0/data/main-menu-ru-ru-v3.json"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            categories = []
            
            # Парсим структуру меню и извлекаем категории
            for section in data:
                if 'childs' in section:
                    for child in section['childs']:
                        if 'shard' in child and 'url' in child:
                            categories.append({
                                'id': child.get('id', len(categories)),
                                'name': child.get('name', 'Без названия'),
                                'url': child.get('shard', ''),
                                'query': child.get('query', '')
                            })
            
            return categories
            
    except Exception as e:
        print(f"Ошибка при получении категорий: {e}")
    
    # Возвращаем кэшированные категории при ошибке
    return [
        {"id": 3192, "name": "Ноутбуки и компьютеры", "url": "catalog/electronics", "query": "subject"},
        {"id": 3281, "name": "Смартфоны и гаджеты", "url": "catalog/smartfony-i-gadzhety", "query": "subject"},
        {"id": 617, "name": "Телевизоры", "url": "catalog/televizory", "query": "subject"},
        {"id": 813, "name": "Красота и здоровье", "url": "catalog/krasota", "query": "subject"},
        {"id": 1680, "name": "Дом и сад", "url": "catalog/dom-i-sad", "query": "subject"},
        {"id": 907, "name": "Одежда", "url": "catalog/odezhda", "query": "category"},
        {"id": 908, "name": "Обувь", "url": "catalog/obuv", "query": "category"}
    ]

# Создаем словарь категорий по ID
CATEGORIES = {cat["id"]: cat for cat in fetch_categories()}
