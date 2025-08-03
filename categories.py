import requests

def fetch_categories():
    """Получаем категории с WB API"""
    try:
        url = "https://static-basket-01.wbbasket.ru/vol0/data/main-menu-ru-ru-v3.json"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            categories = []
            
            # Рекурсивная функция для обхода вложенных категорий
            def parse_categories(section):
                if 'childs' in section:
                    for child in section['childs']:
                        # Фильтруем только категории с shard и query
                        if child.get('shard') and child.get('query'):
                            categories.append({
                                'id': child.get('id', len(categories)),
                                'name': child.get('name', 'Без названия'),
                                'url': child.get('shard', ''),
                                'query': child.get('query', '')
                            })
                        parse_categories(child)
            
            for section in data:
                parse_categories(section)
            
            return categories
            
    except Exception as e:
        print(f"Ошибка при получении категорий: {e}")
    
    # Возвращаем кэшированные категории при ошибке
    return [
        {"id": 3192, "name": "Ноутбуки и компьютеры", "url": "/catalog/elektronika/noutbuki-pereferiya/noutbuki-ultrabuki", "query": "cat=9103"},
        {"id": 3281, "name": "Смартфоны и гаджеты", "url": "/catalog/elektronika/smartfony-i-gadzhety", "query": "cat=9103"},
        {"id": 617, "name": "Телевизоры", "url": "/catalog/elektronika/televizory", "query": "cat=9103"},
        {"id": 813, "name": "Красота и здоровье", "url": "/catalog/krasota", "query": "cat=9103"},
        {"id": 1680, "name": "Дом и сад", "url": "/catalog/dom-i-dacha", "query": "cat=9103"},
        {"id": 907, "name": "Одежда", "url": "/catalog/odezhda", "query": "cat=9103"},
        {"id": 908, "name": "Обувь", "url": "/catalog/obuv", "query": "cat=9103"}
    ]

# Создаем словарь категорий по ID
CATEGORIES = {cat["id"]: cat for cat in fetch_categories()}
