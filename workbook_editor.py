"""Встроенная таблица Windows: просмотр .xlsx и ограниченная правка без Excel."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemDelegate, QAbstractItemView, QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout)

from excel_html import css_color, format_value, theme_palette
from workbook_document import WorkbookDocument


class WorkbookEditor(QDialog):
    def __init__(self, path, mode='prices', editable=True, parent=None):
        super().__init__(parent)
        self.document = WorkbookDocument(path, mode, editable)
        self.validation_error = False
        self.palette_colors = theme_palette(self.document.workbook)
        self.setWindowTitle(f'{Path(path).name} — Мониторинг цен')
        self.resize(1060, 720)
        self.setMinimumSize(640, 420)
        layout = QVBoxLayout(self)
        title = QLabel(Path(path).name)
        title.setStyleSheet('font-size:18px;font-weight:600')
        title.setTextFormat(Qt.PlainText)
        layout.addWidget(title)
        self.hint = QLabel('Изменяйте ссылки магазинов; артикулы и названия защищены.' if mode == 'links' else
                           'Изменяйте только наши цены НОСИМО; остальные ячейки защищены.')
        if not editable or (mode == 'prices' and not self.document.table):
            self.hint.setText('Только просмотр. Для правки выберите исходную таблицу мониторинга после завершения сбора.')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Найти артикул или текст…')
        self.search.setAccessibleName('Поиск по таблице')
        self.search.textChanged.connect(self.find_text)
        toolbar.addWidget(self.search, 1)
        next_button = QPushButton('Найти дальше')
        next_button.clicked.connect(lambda: self.find_text(self.search.text(), advance=True))
        toolbar.addWidget(next_button)
        layout.addLayout(toolbar)
        self.tabs = QTabWidget()
        self.grids = {}
        for sheet in self.document.workbook:
            grid = QTableWidget(sheet.max_row, sheet.max_column)
            grid.setObjectName(sheet.title)
            grid.setAccessibleName('Лист ' + sheet.title)
            grid.setSortingEnabled(False)
            grid.setWordWrap(True)
            grid.setSelectionMode(QAbstractItemView.SingleSelection)
            grid.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
            grid.setHorizontalHeaderLabels([self._letter(c) for c in range(1, sheet.max_column + 1)])
            self.tabs.addTab(grid, sheet.title)
            self.grids[sheet.title] = grid
            self.populate(sheet.title)
            grid.itemChanged.connect(lambda item, name=sheet.title: self.item_changed(name, item))
        self.tabs.setCurrentIndex(self.document.workbook.index(self.document.workbook.active))
        layout.addWidget(self.tabs, 1)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setAccessibleName('Состояние таблицы')
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.save_button = QPushButton('Сохранить')
        self.save_button.setObjectName('primary')
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_document)
        buttons.addWidget(self.save_button)
        close_button = QPushButton('Закрыть')
        close_button.clicked.connect(self.reject)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        QShortcut(QKeySequence.Save, self, activated=self.save_document)
        QShortcut(QKeySequence.Find, self, activated=self.search.setFocus)

    @staticmethod
    def _letter(col):
        from openpyxl.utils import get_column_letter
        return get_column_letter(col)

    def current_grid(self):
        return self.tabs.currentWidget()

    def cell_text(self, name, row, col, editing=False):
        cell = self.document.workbook[name].cell(row, col)
        value = self.document.displayed_value(name, row, col)
        if editing and self.document.can_edit(name, row, col):
            return '' if cell.value is None else str(cell.value)
        return format_value(value, cell.number_format)

    def populate(self, name):
        ws, grid = self.document.workbook[name], self.grids[name]
        grid.blockSignals(True)
        grid.clearSpans()
        indexed = getattr(self.document.workbook, '_colors', None)
        for row in ws:
            for cell in row:
                item = QTableWidgetItem(self.cell_text(name, cell.row, cell.column))
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | (
                    Qt.ItemIsEditable if self.document.can_edit(name, cell.row, cell.column) else Qt.NoItemFlags))
                font = QFont(cell.font.name or 'Calibri')
                font.setPointSizeF(cell.font.sz or 11)
                font.setBold(bool(cell.font.bold)); font.setItalic(bool(cell.font.italic))
                item.setFont(font)
                if cell.fill.fill_type == 'solid':
                    color = css_color(cell.fill.fgColor, self.palette_colors, indexed=indexed)
                    if color:
                        item.setBackground(QColor(color))
                color = css_color(cell.font.color, self.palette_colors, indexed=indexed)
                if color:
                    item.setForeground(QColor(color))
                horizontal = {'right': Qt.AlignRight, 'center': Qt.AlignHCenter}.get(cell.alignment.horizontal, Qt.AlignLeft)
                if isinstance(cell.value, (int, float)) and cell.alignment.horizontal in (None, 'general'):
                    horizontal = Qt.AlignRight
                item.setTextAlignment(horizontal | Qt.AlignVCenter)
                if cell.data_type == 'f':
                    item.setToolTip('Формула: ' + cell.value + '\nПоказано сохранённое значение; программа не вычисляет формулы Excel.')
                else:
                    tip = str(cell.value or '')
                    if self.document.can_edit(name, cell.row, cell.column):
                        tip += '\nДвойной щелчок или F2 — изменить. Ctrl+S — сохранить.'
                    item.setToolTip(tip)
                grid.setItem(cell.row - 1, cell.column - 1, item)
        widths, hidden = {}, set()
        for dim in ws.column_dimensions.values():
            start = dim.min or 1
            end = dim.max or start
            for col in range(start, min(end, ws.max_column) + 1):
                widths[col] = dim.width
                if dim.hidden:
                    hidden.add(col)
        for col in range(1, ws.max_column + 1):
            width = round((widths.get(col) or ws.sheet_format.defaultColWidth or 13) * 7 + 5)
            for row in range(min(ws.max_row, 200)):
                item = grid.item(row, col - 1)
                if item:
                    metrics = QFontMetricsF(item.font())
                    parts = item.text().split() if row < 2 else item.text().splitlines()
                    width = max(width, min(460, int(max((metrics.horizontalAdvance(p) for p in parts), default=0)) + 16))
            grid.setColumnWidth(col - 1, max(55, width))
            grid.setColumnHidden(col - 1, col in hidden)
        for row in range(1, ws.max_row + 1):
            dim = ws.row_dimensions.get(row)
            height = dim.height if dim and dim.height else ws.sheet_format.defaultRowHeight or 15
            grid.setRowHeight(row - 1, max(22, round(height * 4 / 3)))
            grid.setRowHidden(row - 1, bool(dim and dim.hidden))
        for merged in ws.merged_cells.ranges:
            grid.setSpan(merged.min_row - 1, merged.min_col - 1,
                         merged.max_row - merged.min_row + 1, merged.max_col - merged.min_col + 1)
        grid.blockSignals(False)

    def item_changed(self, name, item):
        row, col = item.row() + 1, item.column() + 1
        try:
            self.document.set_value(name, row, col, item.text())
            self.validation_error = False
            self.status.setText('Есть несохранённые изменения.' if self.document.dirty else '')
            self.status.setStyleSheet('')
        except ValueError as error:
            self.validation_error = True
            self.status.setText(str(error))
            self.status.setStyleSheet('color:#b42318')
        grid = self.grids[name]
        grid.blockSignals(True)
        item.setText(self.cell_text(name, row, col))
        grid.blockSignals(False)
        self.save_button.setEnabled(self.document.dirty)

    def commit_active_editor(self):
        self.validation_error = False
        for grid in self.grids.values():
            editor = grid.findChild(QLineEdit)
            if editor and editor.isVisible():
                grid.commitData(editor)
                grid.closeEditor(editor, QAbstractItemDelegate.NoHint)
        return not self.validation_error

    def save_document(self):
        if not self.commit_active_editor():
            return False
        try:
            backup = self.document.save()
        except (OSError, ValueError) as error:
            self.status.setText('Не удалось сохранить: ' + str(error))
            self.status.setStyleSheet('color:#b42318')
            return False
        self.status.setStyleSheet('')
        self.status.setText('Сохранено. Резервная копия: ' + str(backup) if backup else 'Изменений нет.')
        self.save_button.setEnabled(False)
        for name in self.grids:
            self.populate(name)
        return True

    def find_text(self, text, advance=False):
        if not text:
            return
        grid = self.current_grid()
        matches = grid.findItems(text, Qt.MatchContains)
        if not matches:
            self.status.setText('Ничего не найдено.')
            return
        current = grid.currentItem()
        index = (matches.index(current) + 1) % len(matches) if advance and current in matches else 0
        grid.setCurrentItem(matches[index])
        grid.scrollToItem(matches[index])
        self.status.setText(f'Найдено ячеек: {len(matches)}')

    def reject(self):
        if not self.commit_active_editor():
            return
        if self.document.dirty:
            answer = QMessageBox.question(self, 'Несохранённые изменения', 'Сохранить изменения перед закрытием?',
                                          QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if answer == QMessageBox.Cancel or (answer == QMessageBox.Save and not self.save_document()):
                return
        self.document.close()
        super().reject()
