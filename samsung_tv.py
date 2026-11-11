"""Каталог samsungstore.ru: только СПБ, полный артикул из карточки, без браузерного профиля."""
import asyncio
import json
import re
from urllib.parse import quote

from matching import norm
from stores import Result, StoreError

BASE = 'https://www.samsungstore.ru'
CATALOG = BASE + '/catalog/televizory/'
CITY = 'Санкт-Петербург'
COOKIES = 'CITY_CODE=spb; CITY_NAME=' + quote(CITY)


def page_data(html):
    match = re.search(r'<script\b[^>]*\bid=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.S)
    try:
        data = json.loads(match[1]) if match else None
        region = data['props']['props']['currentRegion']['REGION_CODE']
        if region != 'spb':
            raise StoreError(f'неверный регион samsungstore: {region}; требуется Санкт-Петербург')
        return data['props']['pageProps']
    except (KeyError, TypeError, ValueError) as e:
        raise StoreError('не удалось подтвердить регион и данные samsungstore') from e


def product_result(product, url):
    price_data = product.get('PRICE') or {}
    if not str(price_data.get('PRICE_TYPE', '')).startswith('spb_'):
        raise StoreError('не удалось подтвердить цену Санкт-Петербурга')
    price = price_data.get('VALUE')
    order = product.get('ORDER_TYPE')
    if order not in ('ORDER', 'NOT_AVAILABLE', 'SUBSCRIBE', 'PREORDER'):
        raise StoreError(f'неизвестный статус наличия samsungstore: {order}')
    if order != 'ORDER':
        return Result(None, url, f'{CITY}: нет в наличии ({order})')
    if not product.get('VISIBLE_PRICE') or not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        raise StoreError('нет подтверждённой цены samsungstore СПБ')
    return Result(int(price), url, CITY)


class SamsungTV:
    def __init__(self, client):
        self.client = client
        self.items = None
        self.products = {}

    async def get(self, url, params=None):
        try:
            response = await asyncio.wait_for(
                self.client.get(url, params=params, headers={'Cookie': COOKIES}), timeout=90)
        except asyncio.TimeoutError as e:
            raise StoreError('samsungstore СПБ: превышено время загрузки страницы (90 секунд)') from e
        if response.status_code != 200:
            raise StoreError(f'samsungstore СПБ HTTP {response.status_code}')
        # Не принимаем редирект на посторонний сайт.
        if response.url.host != 'www.samsungstore.ru' or response.url.scheme != 'https':
            raise StoreError('неожиданный адрес samsungstore')
        return page_data(response.text)

    async def load(self):
        items, seen = [], set()
        current, last, total = 1, 1, None
        while current <= last:
            data = await self.get(CATALOG, params={'page': current})
            queries = data.get('initialState', {}).get('api', {}).get('queries', {})
            query = next((q for q in queries.values() if q.get('endpointName') == 'getProducts'), None)
            if not query or query.get('status') != 'fulfilled':
                raise StoreError('не получен каталог samsungstore СПБ')
            page = query.get('data') or {}
            try:
                last = int(page['LAST_PAGE'])
                actual = int(page['CURRENT_PAGE'])
                count = int(page['TOTAL'])
                products = page['ITEMS']
            except (KeyError, TypeError, ValueError) as e:
                raise StoreError('изменился формат каталога samsungstore') from e
            if actual != current or not 1 <= last <= 100 or not isinstance(products, list) or not products:
                raise StoreError('неполная страница каталога samsungstore')
            if total is None:
                total = count
            if total != count:
                raise StoreError('каталог изменился во время загрузки; повторите сбор')
            for product in products:
                code = str(product.get('KOD', ''))
                if not code.isdigit() or code in seen:
                    raise StoreError('повторная или некорректная карточка каталога samsungstore')
                seen.add(code)
                items.append(product)
            current += 1
            if current <= last:
                await asyncio.sleep(0.3)
        if len(items) != total:
            raise StoreError('загружен не весь каталог samsungstore; цены не обновлены')
        self.items = items

    async def product(self, code):
        if code not in self.products:
            url = f'{BASE}/products/productID{code}/'
            data = await self.get(url)
            product = data.get('product')
            if not isinstance(product, dict) or not product.get('ARTICLE'):
                raise StoreError('в карточке samsungstore нет полного артикула')
            self.products[code] = product
            await asyncio.sleep(0.3)
        return self.products[code]

    async def find(self, article):
        if self.items is None:
            await self.load()
        candidates = []
        # Название каталога сокращено (QE43LS03FA), поэтому окончательная проверка — ARTICLE карточки.
        # Читаем все карточки: нельзя объявлять товар отсутствующим по сокращённому названию.
        for item in self.items:
            models = re.findall(r'\b[A-Z]{1,3}\d{2}[A-Z0-9]{4,}\b', item.get('TITLE', '').upper())
            if models and not any(norm(article).startswith(model) for model in models):
                continue
            code = str(item['KOD'])
            product = await self.product(code)
            if norm(product['ARTICLE']) == norm(article):
                candidates.append(product_result(product, f'{BASE}/products/productID{code}/'))
        priced = [r for r in candidates if r.price is not None]
        return min(priced, key=lambda r: r.price) if priced else (candidates[0] if candidates else
            Result(None, CATALOG, f'{CITY}: артикул не найден в каталоге'))
