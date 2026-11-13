"""Цены СПБ в копии исходного шаблона: прежняя колонка М.Видео, исходное оформление."""
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter, column_index_from_string

from excel import write_table
from workbook_layout import retain_columns

# Совместимость с первой тестовой сборкой: перенос только цен из компактного отчёта.
COMPACT_HEADERS = ['Артикул', 'НОСИМО', 'samsungstore.ru · Санкт-Петербург', 'Разница, ₽',
                   'Разница, %', 'Ссылка', 'Статус', 'Обновлено']
HEADER = 'Розничная цена samsungstore СПБ'


def write_report(table, source, destination, results, previous_source=None):
    original = openpyxl.load_workbook(source, read_only=True)
    try:
        header = original.active[f"{table['price_cols']['samsungstore']}1"].value
        clear_source_prices = 'samsungstore' not in str(header).lower()
    finally:
        original.close()
    previous_table = None
    previous = source
    previous_path = destination if Path(destination).exists() else previous_source
    if previous_path and Path(previous_path).exists():
        wb = openpyxl.load_workbook(previous_path, read_only=True)
        try:
            headers = [c.value for c in next(wb.active.iter_rows(max_row=1))]
            if headers == COMPACT_HEADERS:
                previous_table = dict(table, first_row=2, article_col='A',
                                      price_cols={'samsungstore': 'C'})
            else:
                cols = [get_column_letter(i) for i, text in enumerate(headers, 1)
                        if 'samsungstore' in str(text).lower()]
                if len(cols) != 1:
                    raise ValueError('Не найдена однозначная колонка samsungstore в прежнем результате СПБ')
                # В полном отчёте сохраняются заголовок и расположение колонки артикула.
                articles = [get_column_letter(i) for i, text in enumerate(headers, 1)
                            if 'артикул' in str(text).lower()]
                if len(articles) != 1:
                    raise ValueError('Не найдена однозначная колонка артикула в прежнем результате СПБ')
                previous_table = dict(table, article_col=articles[0], price_cols={'samsungstore': cols[0]})
            previous = previous_path
        finally:
            wb.close()
    keep = [column_index_from_string(table[key]) for key in ('article_col', 'base_col')]
    keep.append(column_index_from_string(table['price_cols']['samsungstore']))
    return write_table(table, previous, destination, results, base_src_path=source,
                       previous_table=previous_table,
                       column_headers={'samsungstore': HEADER}, preserve_view=True,
                       clear_source_prices=clear_source_prices,
                       worksheet_transform=lambda ws, cached: retain_columns(ws, keep, cached))
