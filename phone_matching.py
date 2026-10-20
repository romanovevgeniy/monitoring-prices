"""Сопоставление строк таблицы смартфонов/планшетов/часов/наушников с названиями товаров на сайтах.

Артикулы в таблице внутренние (SM-A165F04128BLK21S), на сайтах их нет. Поэтому сравниваем по смыслу:
модель («S26 Ultra», «Tab A11+», «Watch8 Classic», «Buds 4 Pro»), память, связь (LTE / Wi-Fi) и размер часов.
Важно не путать соседние модели: S26 ≠ S26+ ≠ S26 Ultra ≠ S26 FE, Buds 4 ≠ Buds 4 Pro, Watch Ultra ≠ Watch Ultra 2.
"""
import re
from dataclasses import dataclass
from typing import Optional

# Слова, после которых модель уже другая (S26 → S26 Ultra / S26+ / S26 FE …)
VARIANTS = ("ultra", "plus", "+", "fe", "lite", "classic", "pro", "edge", "max", "mini", "slim", "flip", "fold")
# Не новые товары и аксессуары
BAD_WORDS = ("б/у", "бу ", "b-u", "уцен", "utsen", "восстановл", "как новый", "kak-novyj", "чехол", "стекло", "пленк",
             "ремешок", "зарядн", "кабель", "держател", "подставк", "аксессуар")
TRANSLATE = [("ультра", "ultra"), ("плюс", "+"), (" plus", "+"), ("классик", "classic"), ("лайт", "lite"),
             ("про ", "pro "), ("эдж", "edge"), ("флип", "flip"), ("фолд", "fold"), ("вотч", "watch"),
             ("бадс", "buds"), ("таб ", "tab ")]
# Русские буквы, похожие на латинские, рядом с цифрами («А37» набрано по-русски)
HOMOGLYPHS = str.maketrans("АВСЕНКМОРТХавсенкмортх", "ABCEHKMOPTXabcehkmoptx")
NOISE = ("samsung", "galaxy", "смартфон", "планшет", "умные", "смарт-часы", "смарт часы", "наушники", "беспроводные",
         "tws", "true wireless", "dual sim", "специальная версия", "(рст)", "рст", "smartfon", "planshet", "naushniki",
         "besprovodnye", "umnye", "chasy", "smart-chasy")

# «12/256GB», «8+128 ГБ», «12GB/256GB», «256 ГБ», «1 ТБ». Перед ОЗУ не должно быть буквы — иначе «S26+ 256» = 26+256
STORAGE = re.compile(r"(?<![0-9a-zа-я])(\d{1,2})\s*(?:гб|gb)?\s*[/+]\s*(\d{1,4})\s*(тб|tb|гб|gb|г|g)?\b"
                     r"|(?<![0-9a-zа-я])(\d{1,4})\s*(тб|tb|гб|gb)\b", re.I)
SIZE = re.compile(r"(\d{2})\s*(мм|mm)\b", re.I)
CONN = re.compile(r"\b(lte|4g|5g|wi-?fi|esim)\b", re.I)

# цвет в адресах МТС — транслитом (sinij, chernyj …)
COLORS = {"blue": ("blue", "синий", "голуб", "sinij", "goluboj"), "black": ("black", "черн", "chern", "chjern"),
          "silver": ("silver", "серебр", "serebr"), "white": ("white", "бел", "belyj"),
          "green": ("green", "зелен", "zelen"), "gray": ("gray", "grey", "сер", "seryj")}


@dataclass
class Spec:
    family: str               # «s26ultra», «taba11+», «watch8classic»
    storage: Optional[int]    # ГБ
    conn: Optional[str]       # «lte» / «wifi» / None — неважно
    size: Optional[int]       # мм (часы)
    color: Optional[str] = None  # только если цвет написан в строке таблицы («… blue»)


def parse_storage(text):
    """«12/256GB» → 256, «12/1Тб» → 1024, «256 ГБ» → 256, «12Gb, 256Gb» (samsungstore) → 256."""
    found = []
    for m in STORAGE.finditer(text):
        if m.group(2):
            n, unit = int(m.group(2)), m.group(3)
            return n * 1024 if (unit and unit.lower() in ("тб", "tb")) or n in (1, 2) else n
        n, unit = int(m.group(4)), m.group(5)
        found.append(n * 1024 if unit.lower() in ("тб", "tb") else n)
    return max(found) if found else None  # несколько «… Gb» подряд: ОЗУ меньше памяти


def _conn(text):
    found = {c.lower().replace("-", "") for c in CONN.findall(text)}
    if found & {"lte", "4g", "5g", "esim"}:
        return "lte"
    if "wifi" in found:
        return "wifi"
    return None


def _clean(text):
    t = " " + text.lower().replace("ё", "е") + " "
    t = re.sub(r"\(?\b20[2-3]\d\b\)?", " ", t)  # год модели: «Watch Ultra (2025)» — это не «Ultra 2»
    t = re.sub(r"e?sim\s*\+\s*e?sim|nano-?sim|dual\s*sim|\besim\b|\bsim\b", " ", t)  # «eSIM+SIM» — не «Flip7+»
    for a, b in TRANSLATE:
        t = t.replace(a, b)
    t = STORAGE.sub(" ", t)
    t = SIZE.sub(" ", t)
    t = CONN.sub(" ", t)
    for w in NOISE:
        t = t.replace(w, " ")
    return t


def compact(text):
    """Без пробелов и знаков, «+» сохраняем (Tab A11+)."""
    return re.sub(r"[^0-9a-zа-я+]", "", text)


def parse_row(name):
    """Строка таблицы («S26 Ultra 256 гб», «Tab A11+ 128Gb LTE», «Watch 8 Classic 46мм LTE») → Spec."""
    name = re.sub(r"[АВСЕНКМОРТХавсенкмортх](?=\d)", lambda m: m.group(0).translate(HOMOGLYPHS), name)
    size = SIZE.search(name)
    t = _clean(name)
    color = next((c for c, words in COLORS.items() if re.search(r"\b(" + "|".join(words) + r")", t)), None)
    t = re.sub(r"\b(blue|black|silver|gray|grey|green|white|синий|черный|серый|белый)\b", " ", t)
    return Spec(family=compact(t), storage=parse_storage(name), conn=_conn(name),
                size=int(size.group(1)) if size else None, color=color)


def bad(name):
    low = name.lower()
    return any(w in low for w in BAD_WORDS)


def family_in(family, site_text):
    """Модель есть в названии, и за ней не идёт другой вариант (S26 ≠ S26 Ultra) или другая цифра (Ultra ≠ Ultra 2).
    Пробелы и дефисы внутри модели допускаются: «Watch 9» = «Watch9», «Z Fold 8» = «Fold8»."""
    text = _clean(site_text)
    pattern = r"(?<![0-9a-zа-я])" + r"[\s\-]*".join(re.escape(ch) for ch in family)
    for m in re.finditer(pattern, text):
        tail = text[m.end():].lstrip(" -")
        if tail[:1].isdigit() or tail[:1] == "+" or any(re.match(re.escape(v) + r"(?![a-zа-я])", tail) for v in VARIANTS):
            continue
        return True
    return False


def matches(spec, site_name):
    """Подходит ли товар сайта под строку таблицы."""
    if bad(site_name) or not family_in(spec.family, site_name):
        return False
    if spec.storage:
        st = parse_storage(site_name)
        if st is not None and st != spec.storage:
            return False
        if st is None and not spec.family.startswith(("watch", "buds")):
            return False  # у телефона/планшета память должна быть указана
    if spec.size:
        size = SIZE.search(site_name)
        if not size or int(size.group(1)) != spec.size:
            return False
    if spec.color and not any(w in site_name.lower() for w in COLORS[spec.color]):
        return False
    if spec.conn:
        c = _conn(site_name)
        if spec.conn == "lte" and c != "lte":
            return False
        if spec.conn == "wifi" and c == "lte":
            return False
    return True
