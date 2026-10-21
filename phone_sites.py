"""Поиск карточек смартфонов/планшетов/часов/наушников Samsung для автозаполнения ссылок (fill_links.py).

Строка таблицы сопоставляется по смыслу (phone_matching.py): модель, память, связь, размер часов.
Среди подходящих карточек (обычно — разные цвета) берётся самая дешёвая в наличии; в наличии нет — самая дешёвая.

М.Видео — каталог категорий: карточка самого М.Видео, если её нет — самый дешёвый продавец маркетплейса (без зарубежных).
DNS — поиск по модели, цена и наличие — из плиток выдачи.
МТС, samsungstore — обход каталога, название/цена/наличие — со страницы товара (кэшируется).
"""
import asyncio
import re
from urllib.parse import quote

from phone_matching import matches, parse_row
from stores import ld_offer, wait_antibot

MVIDEO_CATEGORIES = ["205", "195", "400", "3967"]  # смартфоны, планшеты, смарт-часы, наушники
MTS_CATEGORIES = ["/catalog/smartfony/samsung/", "/catalog/gadzhety/planshety/samsung/",
                  "/catalog/gadzhety/umnye-veshchi/umnye-chasy/samsung/", "/catalog/aksessuary/naushniki/brand-samsung/"]
SAMSUNGSTORE_CATEGORIES = ["/catalog/smartfony_galaxy/", "/catalog/galaxy_tabs/", "/catalog/galaxy_watches/",
                           "/catalog/naushniki/"]
USED = re.compile(r"b-u|kak-novyj|uczenk|utsenen|vosstanovl", re.I)
# Зарубежные версии у продавцов маркетплейса М.Видео — не российский товар
FOREIGN = re.compile(r"global|глобал|\(eu\)|\beu\b|\bhk\b|india|индия|\(cn\)|китай|международ|/ds\b|\bnf\b", re.I)


class Offer:
    def __init__(self, url, name, price, in_stock):
        self.url, self.name, self.price, self.in_stock = url, name, price, in_stock


def pick(offers):
    """Самая дешёвая в наличии; если в наличии нет — самая дешёвая из всех."""
    priced = [o for o in offers if o.price]
    pool = [o for o in priced if o.in_stock] or priced or offers
    return min(pool, key=lambda o: o.price or 10 ** 12) if pool else None


def query_for(row_name):
    """Строка таблицы → поисковый запрос: «Watch 8 Classic 46мм LTE» → «Samsung Galaxy Watch 8 Classic 46 LTE»."""
    q = re.sub(r"(гб|gb|тб|tb|мм|mm)\b", " ", row_name, flags=re.I)
    q = re.sub(r"^\s*galaxy\s+", "", q.strip(), flags=re.I)
    return "Samsung Galaxy " + re.sub(r"\s+", " ", q).strip()


# ---------- М.Видео ----------

class MVideo:
    def __init__(self, page, catalog_loader):
        self.page, self.catalog_loader = page, catalog_loader
        self.items, self.details_cache = None, {}

    async def details(self, product_id):
        """productDetails карточки (кэш): supplierId — сторонний продавец, isForeign — зарубежная версия, soldOut."""
        if product_id not in self.details_cache:
            d = await self.page.evaluate("async u => await (await fetch(u, {credentials: 'include'})).json()",
                                         f"/bff/pdp/info?productId={product_id}")
            self.details_cache[product_id] = ((d or {}).get("body") or {}).get("productDetails") or {}
            await asyncio.sleep(0.2)
        return self.details_cache[product_id]

    async def is_own(self, product_id):
        """Карточка самого М.Видео — у неё нет стороннего поставщика (supplierId)."""
        return not (await self.details(product_id)).get("supplierId")

    async def find(self, row_name):
        if self.items is None:
            self.items = await self.catalog_loader(self.page, MVIDEO_CATEGORIES)
        spec = parse_row(row_name)
        price = lambda x: (x.get("price") or {}).get("salePrice") or 10 ** 12  # noqa: E731
        cands = sorted((x for x in self.items if matches(spec, x.get("name", ""))), key=price)
        in_stock = [x for x in cands if x.get("status") == "available" and not x.get("soldOut")]
        ordered = in_stock + [x for x in cands if x not in in_stock]
        # 1) карточка самого М.Видео — сначала в наличии, по возрастанию цены
        for x in ordered:
            if await self.is_own(x["productId"]):
                note = "" if x in in_stock else " (сейчас нет в наличии)"
                return f"https://www.mvideo.ru/products/{x['productId']}", f"{len(cands)} карточек, выбрана М.Видео{note}"
        # 2) своей нет — самый дешёвый продавец маркетплейса в наличии, без зарубежных версий: признак isForeign
        #    в карточке (в названии «Global» бывает не написан) и слова Global, EU, HK … в названии
        for x in in_stock:
            d = await self.details(x["productId"])
            if not d.get("isForeign") and not d.get("soldOut") and not FOREIGN.search(x.get("name", "")):
                return (f"https://www.mvideo.ru/products/{x['productId']}",
                        f"{len(cands)} карточек, своей у М.Видео нет — продавец маркетплейса")
        return None, "только зарубежные версии / нет в наличии" if cands else "нет в каталоге М.Видео"


# ---------- DNS ----------

DNS_TILES = """() => [...document.querySelectorAll('.catalog-product')].map(el => {
    const a = el.querySelector('a.catalog-product__name');
    const pr = el.querySelector('.product-buy__price');
    const av = el.querySelector('.order-avail-wrap');
    return [a ? a.href.split('?')[0].split('#')[0] : '', a ? a.innerText.trim() : '',
            pr ? pr.innerText : '', av ? av.innerText : ''];
})"""


class DNS:
    def __init__(self, page):
        self.page = page

    async def find(self, row_name):
        spec = parse_row(row_name)
        await self.page.goto(f"https://www.dns-shop.ru/search/?q={quote(query_for(row_name))}",
                             wait_until="domcontentloaded", timeout=60000)
        await wait_antibot(self.page)
        await self.page.wait_for_timeout(3000)
        offers = []
        for href, name, price, avail in await self.page.evaluate(DNS_TILES):
            if "/product/" in href and matches(spec, name):
                digits = re.sub(r"\D", "", price.split("₽")[0]) if price else ""
                offers.append(Offer(href.replace("/product/analog/", "/product/"), name, int(digits) if digits else None,
                                    "в наличии" in avail.lower()))
        best = pick(offers)
        if not best:
            return None, "не найдено в DNS"
        return best.url, f"{len(offers)} вариантов" + ("" if best.in_stock else ", нет в наличии")


# ---------- МТС и samsungstore (обычные запросы) ----------

class HttpCatalog:
    """Каталог магазина: адреса товаров собираются один раз, страницы товаров — по мере надобности (с кэшем)."""

    def __init__(self, client, base):
        self.client, self.base = client, base
        self.urls, self.info = None, {}

    async def product(self, url):
        if url not in self.info:
            r = await self.client.get(url)
            offer = ld_offer(r.text) if r.status_code == 200 else None
            self.info[url] = Offer(url, offer[2], offer[0], offer[1]) if offer and offer[2] else None
            await asyncio.sleep(0.3)
        return self.info[url]

    async def find_by_pages(self, spec, urls):
        offers = [o for o in [await self.product(u) for u in urls] if o and matches(spec, o.name)]
        return pick(offers), len(offers)


class MTS(HttpCatalog):
    def __init__(self, client):
        super().__init__(client, "https://shop.mts.ru")

    async def load(self):
        urls = []
        for base in MTS_CATEGORIES:
            for n in range(1, 30):
                r = await self.client.get(self.base + (base if n == 1 else f"{base}{n}/"))
                if r.status_code != 200:
                    break
                new = [p for p in dict.fromkeys(re.findall(r'href="(/product/[^"#?]+)"', r.text))
                       if "samsung" in p and not USED.search(p) and self.base + p not in urls]
                if not new:
                    break
                urls += [self.base + p for p in new]
                await asyncio.sleep(0.3)
        self.urls = urls

    @staticmethod
    def slug_text(url):
        """Адрес товара → текст для предварительного отбора: «…-s26-plus-12-256-gb-…» → «s26 plus 12/256 gb»."""
        t = url.rsplit("/", 1)[-1].replace("-", " ")
        return re.sub(r"\b(\d{1,2})(?:gb)? (\d{2,4}|1|2)( ?(?:gb|tb|g))?\b", r"\1/\2\3", t)

    async def find(self, row_name):
        if self.urls is None:
            await self.load()
        spec = parse_row(row_name)
        # отбор по адресу (там модель и память), затем точная проверка по названию со страницы товара
        pre = [u for u in self.urls if matches(spec, self.slug_text(u))]
        best, n = await self.find_by_pages(spec, pre)
        if not best:
            return None, "не найдено в МТС"
        return best.url, f"{n} вариантов" + ("" if best.in_stock else ", нет в наличии")


class SamsungStore(HttpCatalog):
    def __init__(self, client):
        super().__init__(client, "https://www.samsungstore.ru")

    async def load(self):
        urls = []
        for base in SAMSUNGSTORE_CATEGORIES:
            for n in range(1, 30):
                r = await self.client.get(self.base + base + (f"?page={n}" if n > 1 else ""))
                if r.status_code != 200:
                    break
                new = [self.base + f"/products/{pid}/" for pid in dict.fromkeys(re.findall(r"/products/(productID\d+)/", r.text))]
                new = [u for u in new if u not in urls]
                if not new:
                    break
                urls += new
                await asyncio.sleep(0.3)
        self.urls = urls

    async def find(self, row_name):
        if self.urls is None:
            await self.load()
        best, n = await self.find_by_pages(parse_row(row_name), self.urls)  # имена — только на страницах товаров
        if not best:
            return None, "не найдено на samsungstore"
        return best.url, f"{n} вариантов" + ("" if best.in_stock else ", нет в наличии")
