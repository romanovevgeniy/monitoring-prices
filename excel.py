"""Запись цен в копию исходной таблицы: меняем только значения и красную подсветку, остальное форматирование не трогаем."""
from collections import Counter
from copy import copy

import openpyxl
from openpyxl.styles import PatternFill

from config import RECOLOR_RED, RED_RGB, RED_THRESHOLD_PCT
from workbook_io import atomic_save

DASH = "-"


def is_red(cell):
    return cell.fill is not None and cell.fill.fill_type == "solid" and cell.fill.fgColor.rgb == RED_RGB


def column_default_fills(ws, cols, first_row):
    """Обычная (не красная) заливка каждой колонки — та, что встречается чаще всего."""
    result = {}
    for col in cols:
        counter, samples = Counter(), {}
        for r in range(first_row, ws.max_row + 1):
            c = ws[f"{col}{r}"]
            if is_red(c):
                continue
            key = (c.fill.fill_type, c.fill.fgColor.rgb, c.fill.fgColor.theme, c.fill.fgColor.tint)
            counter[key] += 1
            samples.setdefault(key, c.fill)
        result[col] = copy(samples[counter.most_common(1)[0][0]]) if counter else PatternFill()
    return result


def as_number(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def write_table(table, src_path, dst_path, results, base_src_path=None, *,
                previous_table=None, column_headers=None, preserve_view=False, worksheet_transform=None, clear_source_prices=False):
    """results: {(row, store): Result}. Возвращает число изменённых ячеек.
    base_src_path — исходник, откуда берутся цены НОСИМО (из 1С), если src_path — уже собранный ранее результат."""
    current = base_src_path or src_path
    wb = openpyxl.load_workbook(current)
    ws = wb.active
    current_rows = article_rows(ws, table)
    base_col = table["base_col"]
    if clear_source_prices:
        for row in current_rows.values():
            for col in table["price_cols"].values():
                ws[f"{col}{row}"].value = None
    if str(current) != str(src_path):
        old_wb = openpyxl.load_workbook(src_path)
        try:
            old_ws = old_wb.active
            old_table = previous_table or detect_table(src_path) or table
            old_rows = article_rows(old_ws, old_table)
            for article, row in current_rows.items():
                if article not in old_rows:
                    continue
                for store, col in table["price_cols"].items():
                    old_col = old_table["price_cols"].get(store)
                    if old_col:
                        ws[f"{col}{row}"].value = old_ws[f"{old_col}{old_rows[article]}"].value
        finally:
            old_wb.close()
    cols = table["price_cols"]
    for store, header in (column_headers or {}).items():
        ws[f"{cols[store]}1"].value = header
    cached_wb = openpyxl.load_workbook(current, data_only=True)
    cached_ws = cached_wb.active
    default_fill = column_default_fills(ws, cols.values(), table["first_row"])
    red_fill = PatternFill("solid", fgColor=RED_RGB)
    changed = 0
    for (row, store), res in results.items():
        cell = ws[f"{cols[store]}{row}"]
        new = res.price if res.price is not None else DASH
        if cell.value != new:
            cell.value = new
            changed += 1
    # Подсветка: красный — у конкурента дешевле, чем у НОСИМО. Пересчитываем все строки,
    # т.к. цены НОСИМО обновляются из 1С независимо от парсера.
    for row in range(table["first_row"], ws.max_row + 1) if RECOLOR_RED else []:
        base = as_number(cached_ws[f"{base_col}{row}"].value)
        for col in cols.values():
            cell = ws[f"{col}{row}"]
            price = as_number(cell.value)
            should_red = bool(base and price is not None and price < base * (1 - RED_THRESHOLD_PCT / 100))
            if should_red and not is_red(cell):
                cell.fill = copy(red_fill)
            elif not should_red and is_red(cell):
                cell.fill = copy(default_fill[col])
    # Результат открывается обычной таблицей, а не страничным режимом («Страница 1» и синие рамки печати)
    if not preserve_view:
        ws.sheet_view.view = "normal"
    if worksheet_transform:
        worksheet_transform(ws, cached_ws)
    cached_wb.close()
    atomic_save(wb, dst_path)
    wb.close()
    return changed


def article_rows(ws, table):
    rows = {}
    for row in range(table["first_row"], ws.max_row + 1):
        value = ws[f"{table['article_col']}{row}"].value
        article = str(value).strip() if value is not None else ""
        if not article:
            continue
        if article in rows:
            raise ValueError(f"Повторяющийся артикул {article}: строки {rows[article]} и {row}")
        rows[article] = row
    return rows


def detect_table(path):
    """Определение типа и обязательных колонок; неоднозначные заголовки запрещают запись."""
    from openpyxl.utils import get_column_letter
    from config import HEADER_WORDS, TABLES
    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        header = {get_column_letter(c.column): str(c.value).lower()
                  for c in next(wb.active.iter_rows(max_row=1))
                  if c.value is not None and getattr(c, "column", None)}
    finally:
        wb.close()
    joined = " ".join(header.values())

    def find(key):
        cols = [col for col, text in header.items() if any(w in text for w in HEADER_WORDS[key])]
        if len(cols) != 1:
            raise ValueError(f"Не найдена однозначная колонка «{key}». Проверьте заголовки таблицы.")
        return cols[0]

    if len(header) == 3 and 'артикул' in joined and 'samsungstore' in joined and 'носимо' in joined:
        found = dict(TABLES[0], file=str(path), source_template='tv-spb')
        found['article_col'] = find('article')
        found['base_col'] = find('base')
        found['price_cols'] = {'samsungstore': find('samsungstore')}
        return found

    for t in TABLES:
        if not all(w in joined for w in t["signature"]):
            continue
        found = dict(t, file=str(path))
        found["article_col"] = find("article")
        if t.get("name_col"):
            found["name_col"] = find("name")
        found["price_cols"] = {store: find(store) for store in t["price_cols"]}
        found["base_col"] = find("base")
        return found
    return None
