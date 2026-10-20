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
        # Тип таблицы узнаём по словам в заголовках первой строки (в любых колонках)
        "signature": ["артикул", "мвидео", "ozon"],
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
        "signature": ["наименование", "артикул", "мтс"],
        # Автозаполнение ссылок по модели/памяти (артикулы внутренние, на сайтах их нет): phone_sites.py
        "autofill": "phones",
        "first_row": 2,
        "article_col": "C",
        "name_col": "B",
        "price_cols": {"mvideo": "D", "dns": "E", "mts": "F", "samsungstore": "G"},
        "base_col": "H",  # НОСИМО
    },
]

# Колонки в файле ищутся по заголовкам (буквы в TABLES — запасной вариант, если заголовок не найден).
# Так таблица переживает вставку колонок: например, НОСИМО переехало из H в I.
HEADER_WORDS = {
    "article": ("артикул",), "name": ("наименование",),
    "mvideo": ("мвидео", "м.видео"), "dns": ("днс", "dns"), "mts": ("мтс",), "samsungstore": ("nbcom", "samsungstore"),
    "ozon": ("ozon", "озон"), "wb": ("wildberries", "вайлдберриз"), "base": ("носимо",),
}

# Красим ячейку конкурента, если его цена ниже цены НОСИМО (base_col); если уже не ниже — возвращаем обычный цвет
RECOLOR_RED = True
# Красим, если цена конкурента ниже базовой больше чем на столько процентов (0 = любая более низкая цена)
RED_THRESHOLD_PCT = 0.0
RED_RGB = "FFFF0000"

LINKS_FILE = "links.xlsx"
# Страница galaxystore строится из артикула: HW-Q600F/RU -> /product/HW-Q600F-RU/
GALAXYSTORE_URL = "https://galaxystore.ru/product/{}/"
REGION = "Москва"
