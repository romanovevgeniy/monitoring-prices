"""Сопоставление названий товаров с артикулом (ТВ) и разбор цен."""
import re

# Слова, по которым отсекаем аксессуары, уценку и б/у
BAD_WORDS = (
    "уцен", "б/у", "восстановл", "ремонт", "витрин",
    "пульт", "кронштейн", "чехол", "пленк", "плёнк", "стекло", "кабель",
    "подставк", "ножки", "крепление", "запчаст",
)


def norm(s):
    return re.sub(r"[^0-9A-ZА-Я]", "", str(s).upper())


def article_core(article):
    """UE32H5000FUXRU -> UE32H5000FUX, HW-Q600F/RU -> HWQ600F: продавцы часто опускают хвост RU."""
    a = norm(article)
    return a[:-2] if a.endswith("RU") and len(a) > 6 else a


def name_matches(name, article):
    """Модель есть в названии, и за ней не идёт суффикс другой версии (QE55QN90FAUXCE, HW-Q600F/XZ — не РФ)."""
    low = str(name).lower()
    if any(w in low for w in BAD_WORDS):
        return False
    core, n = article_core(article), norm(name)
    for m in re.finditer(re.escape(core), n):
        tail = n[m.end():m.end() + 2]
        if tail == "RU" or not re.match(r"[A-Z]{2}", tail):
            return True
    return False


def parse_rub(text):
    """'21 542 ₽' (с любыми пробелами) -> 21542."""
    digits = re.sub(r"\D", "", str(text))
    return int(digits) if digits else None


def parse_reviews(text):
    m = re.search(r"(\d[\d\s  ]*)\s*отзыв", str(text))
    return int(re.sub(r"\D", "", m.group(1))) if m else 0
