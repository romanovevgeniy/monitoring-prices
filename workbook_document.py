"""Правка разрешённых значений .xlsx без Microsoft Excel, с сохранением оформления."""
from copy import copy
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit

import openpyxl
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import PatternFill

from config import HEADER_WORDS, RED_RGB, RED_THRESHOLD_PCT, TABLES
from excel import as_number, column_default_fills, detect_table, is_red
from workbook_io import atomic_save


def price_value(text):
    text = str(text).strip().replace('₽', '').replace('\u00a0', '').replace('\u202f', '').replace(' ', '')
    if not text:
        return None
    if text == '-':
        return '-'
    if not re.fullmatch(r'\d+(?:[.,]\d{1,2})?', text):
        raise ValueError('Цена: неотрицательное число, не более двух знаков после запятой; пусто или «-».')
    try:
        value = Decimal(text.replace(',', '.'))
    except InvalidOperation as error:
        raise ValueError('Некорректная цена') from error
    if value > 1_000_000_000:
        raise ValueError('Цена не должна превышать 1 000 000 000 ₽')
    return int(value) if value == value.to_integral_value() else float(value)


def link_value(text):
    text = str(text).strip()
    if not text or text == '-':
        return text or None
    url = urlsplit(text)
    if url.scheme not in ('http', 'https') or not url.hostname or any(c.isspace() for c in text):
        raise ValueError('Введите ссылку http:// или https://, «-» или оставьте ячейку пустой.')
    return text


class WorkbookDocument:
    def __init__(self, path, mode='prices', editable=True):
        if mode not in ('prices', 'links'):
            raise ValueError('Неизвестный режим таблицы')
        self.path = Path(path)
        self.mode, self.editable = mode, editable
        self.digest = self.fingerprint()
        self.workbook = openpyxl.load_workbook(self.path)
        self.cached = openpyxl.load_workbook(self.path, data_only=True)
        self.original = {}
        self.table = None
        self.price_sheet = self.workbook.active.title
        if mode == 'prices':
            try:
                self.table = detect_table(self.path)
            except ValueError:
                self.table = None  # неизвестный формат всё равно доступен для просмотра

    def fingerprint(self):
        return hashlib.sha256(self.path.read_bytes()).digest()

    @property
    def dirty(self):
        return bool(self.original)

    def can_edit(self, sheet, row, col):
        if not self.editable:
            return False
        ws = self.workbook[sheet]
        cell = ws.cell(row, col)
        if isinstance(cell, MergedCell):
            return False
        if self.mode == 'prices':
            return bool(self.table and sheet == self.price_sheet and row >= self.table['first_row']
                        and cell.column_letter == self.table['base_col']
                        and ws[f"{self.table['article_col']}{row}"].value)
        if sheet not in {t['name'] for t in TABLES} or row < 2 or col < 3 or not ws.cell(row, 1).value:
            return False
        header = str(ws.cell(1, col).value or '').lower()
        return any(word in header for store in ('mvideo', 'dns', 'mts', 'samsungstore')
                   for word in HEADER_WORDS[store])

    def set_value(self, sheet, row, col, text):
        if not self.can_edit(sheet, row, col):
            raise ValueError('Эта ячейка доступна только для просмотра.')
        value = price_value(text) if self.mode == 'prices' else link_value(text)
        cell = self.workbook[sheet].cell(row, col)
        key = (sheet, row, col)
        old = self.original.get(key, cell.value)
        if value == old:
            self.original.pop(key, None)
        else:
            self.original.setdefault(key, old)
        cell.value = value
        if self.mode == 'links':
            cell.hyperlink = value if isinstance(value, str) and value.startswith(('http://', 'https://')) else None

    def displayed_value(self, sheet, row, col):
        cell = self.workbook[sheet].cell(row, col)
        if cell.data_type == 'f':
            value = self.cached[sheet].cell(row, col).value
            return cell.value if value is None else value
        return cell.value

    def recolor(self):
        if self.mode != 'prices' or not self.table:
            return
        ws = self.workbook[self.price_sheet]
        cols = self.table['price_cols'].values()
        default_fills = column_default_fills(ws, cols, self.table['first_row'])
        rows = {row for sheet, row, _ in self.original if sheet == self.price_sheet}
        for row in rows:
            base = as_number(ws[f"{self.table['base_col']}{row}"].value)
            for col in cols:
                cell = ws[f'{col}{row}']
                value = self.displayed_value(self.price_sheet, row, cell.column)
                price = as_number(value)
                red = bool(base and price is not None and price < base * (1 - RED_THRESHOLD_PCT / 100))
                if red:
                    cell.fill = PatternFill('solid', fgColor=RED_RGB)
                elif is_red(cell):
                    cell.fill = copy(default_fills[col])

    def save(self):
        if not self.dirty:
            return None
        if self.fingerprint() != self.digest:
            raise ValueError('Файл изменён другой программой. Закройте таблицу и откройте её заново перед правкой.')
        self.recolor()
        folder = self.path.parent / ('Резервные копии ссылок' if self.mode == 'links' else 'Резервные копии таблиц')
        folder.mkdir(parents=True, exist_ok=True)
        backup = folder / f'{self.path.stem} {datetime.now():%Y-%m-%d %H-%M-%S-%f}{self.path.suffix}'
        shutil.copy2(self.path, backup)
        atomic_save(self.workbook, self.path)
        self.digest = self.fingerprint()
        self.original.clear()
        return backup

    def close(self):
        self.workbook.close()
        self.cached.close()
