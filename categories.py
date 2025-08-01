# Получаем категории с WB API
import requests

def fetch_categories():
    try:
        response = requests.get(
            "https://www.wildberries.ru/webapi/menu/main-menu-ru-ru.json",
            timeout=10
        )
        return response.json()
    except Exception:
        # Возвращаем кэшированные категории при ошибке
        return [
            {"id": 3192, "name": "Ноутбуки и компьютеры", "url": "elektronika/noutbuki-pereferiya"},
            {"id": 3281, "name": "Смартфоны и гаджеты", "url": "elektronika/smartfony-i-gadzhety"},
            {"id": 617, "name": "Телевизоры", "url": "elektronika/televizory"},
            {"id": 813, "name": "Красота и здоровье", "url": "krasota-i-zdorove"},
            {"id": 1680, "name": "Дом и сад", "url": "dom-i-dacha"},
            {"id": 907, "name": "Одежда", "url": "zhenshchinam/odezhda"},
            {"id": 908, "name": "Обувь", "url": "zhenshchinam/obuv"},
        ]

CATEGORIES = {cat["id"]: cat for cat in fetch_categories()}
