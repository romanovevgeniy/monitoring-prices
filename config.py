"""Описание таблиц мониторинга: где артикулы и в какие колонки писать цены каждого магазина."""

# Магазины: ключ -> подпись колонки в файле ссылок
STORES = {
    "mvideo": "М.Видео",
    "dns": "DNS",
    "mts": "МТС",
    "samsungstore": "samsungstore.ru (Nbcom)",
    "galaxystore": "galaxystore.ru (НОСИМО)",
    "ozon": "Ozon",
    "wb": "Wildberries",
}

TABLES = [
    {
        "name": "ТВ",
        "file": "Мониторинг ТВ и акустики 2025.xlsx",
        # По этим заголовкам узнаём тип таблицы в произвольном файле (ячейка -> фрагмент текста)
        "signature": {"A1": "артикул", "B1": "мвидео", "F1": "ozon"},
        # Автозаполнение ссылок М.Видео: категории каталога (поиск М.Видео для автоматизации не работает)
        "mvideo_categories": ["65", "2547"],  # телевизоры, саундбары
        "first_row": 3,
        "article_col": "A",
        "name_col": None,
        "price_cols": {"mvideo": "B", "dns": "D", "ozon": "F", "wb": "G"},
        "base_col": "I",  # НОСИМО — из 1С или кнопкой «Цены НОСИМО» (galaxystore.ru)
    },
    {
        "name": "Смартфоны",
        "file": "Мониторинг_смартфоны_планшеты_09_2025_003.xlsx",
        "signature": {"B1": "наименование", "C1": "артикул", "F1": "мтс"},
        # Автозаполнение ссылок по модели/памяти (артикулы внутренние, на сайтах их нет): phone_sites.py
        "autofill": "phones",
        "first_row": 2,
        "article_col": "C",
        "name_col": "B",
        "price_cols": {"mvideo": "D", "dns": "E", "mts": "F", "samsungstore": "G"},
        "base_col": "H",  # НОСИМО
    },
]

# Красим ячейку конкурента, если его цена ниже цены НОСИМО (base_col); если уже не ниже — возвращаем обычный цвет
RECOLOR_RED = True
# Красим, если цена конкурента ниже базовой больше чем на столько процентов (0 = любая более низкая цена)
RED_THRESHOLD_PCT = 0.0
RED_RGB = "FFFF0000"

LINKS_FILE = "links.xlsx"
# Страница galaxystore строится из артикула: HW-Q600F/RU -> /product/HW-Q600F-RU/
GALAXYSTORE_URL = "https://galaxystore.ru/product/{}/"
REGION = "Москва"
