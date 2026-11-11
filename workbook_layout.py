"""Удаление колонок из копии шаблона с переносом его размеров и объединений."""
from copy import copy
import re

from openpyxl.formula import Tokenizer
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.worksheet.cell_range import CellRange
from openpyxl.worksheet.print_settings import PrintArea


CELL = re.compile(r'(\$?)([A-Z]{1,3})(\$?\d+)')


def remap_formula(formula, columns, sheet_title, qualified_only=False):
    tokens = Tokenizer(formula).items
    for token in tokens:
        if token.type != 'OPERAND' or token.subtype != 'RANGE':
            continue
        prefix, sep, reference = token.value.rpartition('!')
        if qualified_only and not sep:
            continue
        if sep and prefix.strip("'").replace("''", "'") != sheet_title:
            continue
        reference = reference if sep else token.value
        parts = reference.split(':')
        matches = [CELL.fullmatch(p) for p in parts]
        if not all(matches):
            # Имена диапазонов не меняются. Ссылки на целые удаляемые колонки требуют пересчёта.
            if ':' in reference:
                raise ValueError('формула ссылается на удаляемый диапазон')
            continue
        indices = [column_index_from_string(m[2]) for m in matches]
        if any(i not in columns for i in range(min(indices), max(indices) + 1)):
            raise ValueError('формула ссылается на удаляемые колонки')
        mapped = ':'.join(m[1] + get_column_letter(columns[i]) + m[3] for m, i in zip(matches, indices))
        token.value = (prefix + '!' if sep else '') + mapped
    return '=' + ''.join(t.value for t in tokens)


def retain_columns(ws, keep, cached_ws):
    keep = sorted(set(keep))
    columns = {old: new for new, old in enumerate(keep, 1)}

    def map_range(value):
        r = CellRange(str(value))
        included = [c for c in keep if r.min_col <= c <= r.max_col]
        if not included:
            return None
        return CellRange(min_col=columns[included[0]], max_col=columns[included[-1]],
                         min_row=r.min_row, max_row=r.max_row)

    dimensions = {columns[c]: copy(ws.column_dimensions[get_column_letter(c)]) for c in keep}
    merged = [map_range(r) for r in ws.merged_cells.ranges
              if all(c in columns for c in range(r.min_col, r.max_col + 1))]
    print_area = [map_range(r) for r in PrintArea.from_string(ws.print_area).ranges] if ws.print_area else []
    auto_filter = map_range(ws.auto_filter.ref) if ws.auto_filter.ref else None
    def rewrite_cell(cell, cache, qualified_only=False):
        if cell.data_type != 'f':
            return
        try:
            cell.value = remap_formula(cell.value, columns, ws.title, qualified_only)
        except ValueError as error:
            value = cache[cell.coordinate].value
            if value is None:
                raise ValueError(f'Пересчитайте исходную таблицу в Excel: {cell.coordinate} — {error}') from error
            cell.value = value

    for row in ws:
        for cell in row:
            if cell.column in columns:
                rewrite_cell(cell, cached_ws)
    for other in ws.parent.worksheets:
        if other is ws:
            continue
        for row in other:
            for cell in row:
                rewrite_cell(cell, cached_ws.parent[other.title], qualified_only=True)
    for name in ws.parent.defined_names.values():
        if name.attr_text:
            name.attr_text = remap_formula('=' + name.attr_text, columns, ws.title, qualified_only=True)[1:]
    # Объединения восстанавливаются после удаления, иначе остаются старые координаты.
    for r in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(r))
    for col in range(ws.max_column, 0, -1):
        if col not in columns:
            ws.delete_cols(col)
    ws.column_dimensions.clear()
    for index, dim in dimensions.items():
        dim.index = get_column_letter(index)
        dim.min = dim.max = index
        ws.column_dimensions[dim.index] = dim
    for r in merged:
        ws.merge_cells(str(r))
    if print_area:
        ws.print_area = [str(r) for r in print_area if r]
    if ws.auto_filter.ref:
        ws.auto_filter.ref = str(auto_filter) if auto_filter else None
    if ws.freeze_panes:
        cell = CELL.fullmatch(ws.freeze_panes)
        if cell:
            col = column_index_from_string(cell[2])
            position = sum(c < col for c in keep) + 1
            ws.freeze_panes = get_column_letter(position) + cell[3].lstrip('$')
    for formatting in list(ws.conditional_formatting):
        ranges = [map_range(r) for r in formatting.sqref.ranges]
        rules = ws.conditional_formatting[formatting]
        del ws.conditional_formatting[formatting]
        mapped = ' '.join(str(r) for r in ranges if r)
        if mapped:
            for rule in rules:
                rule.formula = [remap_formula('=' + f.lstrip('='), columns, ws.title)[1:] for f in (rule.formula or [])]
                ws.conditional_formatting.add(mapped, rule)
