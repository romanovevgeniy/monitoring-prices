"""Получение цены по каждому магазину.

Каждая функция возвращает Result. price=None — товара нет / не найден (в таблицу пишется «-»).
Исключение — ошибка (сайт не ответил, антибот): старое значение в таблице не трогаем.
"""
import asyncio
import json
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import httpx

from matching import name_matches, parse_reviews, parse_rub

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0 Safari/537.36")

# Сколько карточек Ozon открывать (проверка наличия и зарубежных предложений)
OZON_MAX_PRODUCT_PAGES = 15
# Сколько первых плиток выдачи маркетплейса (по релевантности) рассматривать
MARKETPLACE_TOP_N = 15
# Отбрасываем подозрительно дешёвые предложения: ниже этой доли от ориентира (цена НОСИМО или прошлая)
MIN_PRICE_RATIO = 0.4


@dataclass
class Result:
    price: Optional[int]
    url: str = ""
    note: str = ""


class StoreError(Exception):
    pass


# ---------- JSON-LD (galaxystore, МТС, samsungstore, DNS) ----------

def ld_offer(html):
    """Достаёт (price, in_stock, name) из schema.org Product на странице."""
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        nodes = data.get("@graph", [data]) if isinstance(data, dict) else data
        for node in nodes:
            if not isinstance(node, dict) or node.get("@type") != "Product":
                continue
            offers = node.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if not isinstance(offers, dict) or offers.get("@type") != "Offer":
                continue
            price = offers.get("price")
            avail = str(offers.get("availability", ""))
            in_stock = not avail or "InStock" in avail
            return (int(float(price)) if price not in (None, "") else None), in_stock, node.get("name", "")
    return None


def ld_result(html, url):
    offer = ld_offer(html)
    if offer is None:
        raise StoreError("на странице нет данных о цене (schema.org Product)")
    price, in_stock, _ = offer
    if not price:
        return Result(None, url, "нет в наличии, цена не указана")
    # Нет в наличии, но цена на сайте указана — записываем цену (так ведётся ручной мониторинг)
    return Result(price, url, "" if in_stock else "нет в наличии, цена указана")


async def http_ld(client: httpx.AsyncClient, url, **_):
    r = await client.get(url)
    if r.status_code == 404:
        return Result(None, url, "страница не найдена (404)")
    if r.status_code != 200:
        raise StoreError(f"HTTP {r.status_code}")
    return ld_result(r.text, url)


def make_http_client():
    return httpx.AsyncClient(headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"},
                             follow_redirects=True, timeout=30)


def same_product(site_name, article, model=None):
    """Ссылка ведёт на нужный товар? ТВ — артикул есть в названии. Смартфоны (артикулы внутренние, на сайтах их нет) —
    совпадают модель, память, связь из колонки «Наименование» (как при автозаполнении ссылок)."""
    if model:
        from phone_matching import matches, parse_row
        return matches(parse_row(model), site_name)
    return not article or name_matches(site_name, article)


# ---------- браузерные магазины ----------

ANTIBOT_MARKERS = ("Подозрительная активность", "Доступ ограничен", "Проверяем браузер",
                   "Почти готово", "Antibot", "captcha")


async def wait_antibot(page, max_wait=120):
    """Если показана заглушка антибота — ждём, пока страница пропустит дальше."""
    for _ in range(max_wait // 5):
        try:
            title = await page.title()
            body = (await page.inner_text("body"))[:600]
        except Exception:
            await asyncio.sleep(5)
            continue
        if title.strip(" .") and not any(m.lower() in (title + body).lower() for m in ANTIBOT_MARKERS):
            return
        await asyncio.sleep(5)
    raise StoreError("антибот не пропустил за отведённое время")


async def dns(page, url, article=None, model=None, **_):
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await wait_antibot(page)
    try:
        await page.wait_for_selector('script[type="application/ld+json"]', state="attached", timeout=20000)
    except Exception:
        pass
    html = await page.content()
    offer = ld_offer(html)
    if offer and offer[2] and not same_product(offer[2], article, model):
        raise StoreError(f"ссылка ведёт на другой товар: «{offer[2]}» — проверьте links.xlsx")
    return ld_result(html, url)


MVIDEO_ID = re.compile(r"/products/(?:[^/?#]*-)?(\d{6,})")


async def mvideo(page, url, article=None, model=None, **_):
    m = MVIDEO_ID.search(url)
    if not m:
        raise StoreError("не нашёл id товара в ссылке М.Видео")
    if "mvideo.ru" not in page.url:
        await page.goto("https://www.mvideo.ru/", wait_until="domcontentloaded", timeout=60000)
        await wait_antibot(page)
    status, text = await page.evaluate(
        "async u => { const r = await fetch(u, {credentials: 'include'}); return [r.status, await r.text()] }",
        f"/bff/pdp/info?productId={m.group(1)}")
    if status != 200:
        raise StoreError(f"М.Видео API HTTP {status}")
    body = json.loads(text).get("body") or {}
    details = body.get("productDetails") or {}
    name = details.get("name", "")
    if name and not same_product(name, article, model):
        raise StoreError(f"ссылка ведёт на другой товар: «{name}» — проверьте links.xlsx")
    # Смартфоны: зарубежная версия или распроданное предложение продавца маркетплейса — ссылка устарела
    if model and details.get("supplierId") and (details.get("isForeign") or details.get("soldOut")):
        why = "зарубежная версия" if details.get("isForeign") else "предложение продавца распродано"
        raise StoreError(f"{why} у продавца маркетплейса — обновите ссылки автозаполнением")
    price = ((body.get("productPrices") or {}).get("price") or {}).get("salePrice")
    return Result(int(price), url) if price else Result(None, url, "нет цены / нет в наличии")


def reviews_note(n):
    return f"отзывов: {n}" if n else "без отзывов (с отзывами предложений нет)"


async def wb(page, article, ref_price=None, **_):
    url = f"https://www.wildberries.ru/catalog/0/search.aspx?search={quote(article)}"
    for attempt in range(2):
        try:
            async with page.expect_response(
                    lambda r: "exactmatch" in r.url and "resultset=catalog" in r.url and r.status == 200,
                    timeout=60000) as resp_info:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await wait_antibot(page)
            data = await (await resp_info.value).json()
            break
        except StoreError:
            raise
        except Exception as e:
            if attempt:
                raise StoreError(f"WB не вернул результаты поиска: {e}")
            await asyncio.sleep(10)
    best_rev = best_any = None  # самая низкая цена с отзывами / вообще
    for p in (data.get("products") or [])[:MARKETPLACE_TOP_N]:
        if not name_matches(p.get("name", ""), article) or not p.get("totalQuantity"):
            continue
        prices = [s["price"]["product"] // 100 for s in p.get("sizes", []) if s.get("price", {}).get("product")]
        if not prices:
            continue
        price = min(prices)
        if ref_price and price < ref_price * MIN_PRICE_RATIO:
            continue
        offer = (price, p["id"], p.get("feedbacks") or 0)
        if best_any is None or price < best_any[0]:
            best_any = offer
        if offer[2] and (best_rev is None or price < best_rev[0]):
            best_rev = offer
    best = best_rev or best_any
    if not best:
        return Result(None, url, "нет предложений в наличии")
    return Result(best[0], f"https://www.wildberries.ru/catalog/{best[1]}/detail.aspx", reviews_note(best[2]))


async def _ozon_states(page, prefix):
    return await page.evaluate(
        """p => [...document.querySelectorAll('[id^="state-' + p + '"]')].map(e => e.getAttribute('data-state'))""",
        prefix)


def _texts(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "text" and isinstance(v, str):
                out.append(v)
            else:
                _texts(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _texts(v, out)
    return out


async def _ozon_product_price(page, sku):
    """Цена с Ozon-картой со страницы товара. None — нет в наличии или товар из-за рубежа."""
    await page.goto(f"https://www.ozon.ru/product/{sku}/", wait_until="domcontentloaded", timeout=60000)
    await wait_antibot(page)
    try:
        await page.wait_for_selector('[id^="state-webPrice"]', state="attached", timeout=20000)
    except Exception:
        return None
    # Зарубежные предложения (доплата таможенного платежа) — не российская версия товара
    if "таможен" in (await page.inner_text("body")).lower():
        return None
    for s in await _ozon_states(page, "webPrice"):
        st = json.loads(s or "{}")
        if st.get("isAvailable") is False:
            return None
        # Цена с Ozon-картой (cardPrice); если её нет — обычная цена
        if st.get("cardPrice") or st.get("price"):
            return parse_rub(st.get("cardPrice") or st["price"])
    return None


def _ozon_candidates(items, article, ref_price):
    """Плитки выдачи -> [(цена_в_выдаче, sku, отзывы)] для подходящих товаров."""
    out = []
    for it in items:
        main = it.get("mainState", [])
        name = next((m.get("textDS", {}).get("text", "") for m in main if m.get("id") == "name"), "")
        badge = (it.get("tileImage", {}).get("leftBottomBadgeV2") or {}).get("text", "")
        pv = next((m["priceV2"] for m in main if m.get("type") == "priceV2"), None)
        if not pv or "уцен" in badge.lower() or not name_matches(name, article):
            continue
        tile_price = next((parse_rub(p["text"]) for p in pv.get("price", []) if p.get("textStyle") == "PRICE"), None)
        if not tile_price or (ref_price and tile_price < ref_price * MIN_PRICE_RATIO):
            continue
        reviews = max((parse_reviews(t) for t in _texts(main, [])), default=0)
        out.append((tile_price, str(it.get("sku") or it.get("id")), reviews))
    return out


async def _ozon_grid_items(page):
    return [it for s in await _ozon_states(page, "tileGrid") for it in json.loads(s or "{}").get("items", [])]


async def _ozon_open_search(page, url):
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await wait_antibot(page)
    try:
        await page.wait_for_selector('[id^="state-tileGrid"]', state="attached", timeout=25000)
        return True
    except Exception:
        return False


async def _ozon_collect(page, article, ref_price):
    """Подходящие товары среди первых MARKETPLACE_TOP_N плиток выдачи по релевантности."""
    captured = []

    async def on_resp(r):
        if "composer-api" in r.url or "entrypoint-api" in r.url:
            try:
                ws = (await r.json()).get("widgetStates") or {}
            except Exception:
                return
            for k, v in ws.items():
                if k.startswith("tileGrid"):
                    captured.extend(json.loads(v).get("items", []))

    items = []
    page.on("response", on_resp)
    try:
        if await _ozon_open_search(page, f"https://www.ozon.ru/search/?text={quote(article)}"):
            items = await _ozon_grid_items(page)
            # Первая отрисовка — ~8 плиток, остальные подгружаются при прокрутке
            for _ in range(3):
                if len(items) + len(captured) >= MARKETPLACE_TOP_N:
                    break
                await page.mouse.wheel(0, 3000)
                await page.wait_for_timeout(1500)
    finally:
        page.remove_listener("response", on_resp)
    top = (items + captured)[:MARKETPLACE_TOP_N]
    uniq = {}
    for c in _ozon_candidates(top, article, ref_price):
        if c[1] not in uniq or c[0] < uniq[c[1]][0]:
            uniq[c[1]] = c
    return sorted(uniq.values())


async def ozon(page, article, ref_price=None, **_):
    search_url = f"https://www.ozon.ru/search/?text={quote(article)}"
    candidates = await _ozon_collect(page, article, ref_price)
    page_prices = {}  # цены с картой со страниц товаров (None — не в наличии / зарубежный)
    state = {"opened": 0}

    async def pick(with_reviews):
        best = None
        for tile_price, sku, reviews in candidates:
            if with_reviews and not reviews:
                continue
            # Кандидаты отсортированы по цене в выдаче; если она уже не ниже лучшей найденной — дальше смотреть незачем.
            # Страницу товара открываем ради проверки наличия и зарубежных предложений (с таможенным платежом).
            if best and tile_price >= best[0]:
                return best
            if sku not in page_prices:
                if state["opened"] >= OZON_MAX_PRODUCT_PAGES:
                    if best:
                        return best
                    raise StoreError(f"проверено {state['opened']} карточек — все зарубежные или "
                                     f"не в наличии, проверьте вручную")
                state["opened"] += 1
                page_prices[sku] = await _ozon_product_price(page, sku)
            price = page_prices[sku]
            if price and (best is None or price < best[0]):
                best = (price, sku, reviews)
        return best

    best = await pick(with_reviews=True) or await pick(with_reviews=False)
    if not best:
        note = "нет предложений в наличии" if candidates else "товар не найден в выдаче"
        return Result(None, search_url, note)
    return Result(best[0], f"https://www.ozon.ru/product/{best[1]}/", reviews_note(best[2]))


# Как получаем цену: (функция, нужен_браузер, link — ссылка из links.xlsx / search — поиск по артикулу / auto — адрес из артикула)
STORE_IMPL = {
    "galaxystore": (http_ld, False, "auto"),
    "mts": (http_ld, False, "link"),
    "samsungstore": (http_ld, False, "link"),
    "dns": (dns, True, "link"),
    "mvideo": (mvideo, True, "link"),
    "ozon": (ozon, True, "search"),
    "wb": (wb, True, "search"),
}
