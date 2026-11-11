"""Проверка упакованного Windows-приложения без установленного Office."""
from pathlib import Path
import tempfile

import openpyxl
from openpyxl.styles import Font
from PySide6.QtWidgets import QApplication

from workbook_editor import WorkbookEditor


def run_selftest():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix='monitoring-selftest-') as folder:
        root = Path(folder)
        path = root / 'Таблица без Excel.xlsx'
        wb = openpyxl.Workbook()
        wb.active.append(['Артикул', 'Розничная цена samsungstore СПБ', 'НОСИМО'])
        wb.active.append([None])
        wb.active.append(['TEST', 80, 100])
        wb.active['C3'].font = Font(name='Arial', size=13, bold=True)
        wb.save(path)
        editor = WorkbookEditor(path)
        editor.current_grid().item(2, 2).setText('150')
        if not editor.save_document():
            raise RuntimeError(editor.status.text())
        editor.reject()
        wb = openpyxl.load_workbook(path)
        try:
            if wb.active['C3'].value != 150 or wb.active['C3'].font.name != 'Arial':
                raise RuntimeError('Проверка сохранения цены и оформления не прошла')
        finally:
            wb.close()
        links = root / 'Ссылки без Excel.xlsx'
        wb = openpyxl.Workbook()
        wb.active.title = 'ТВ'
        wb.active.append(['Артикул', 'Наименование', 'М.Видео', 'DNS'])
        wb.active.append(['TEST', 'TV', None, None])
        wb.save(links)
        editor = WorkbookEditor(links, mode='links')
        editor.current_grid().item(1, 2).setText('https://www.mvideo.ru/products/123456')
        if not editor.save_document():
            raise RuntimeError(editor.status.text())
        editor.reject()
        wb = openpyxl.load_workbook(links)
        try:
            if wb.active['C2'].value != 'https://www.mvideo.ru/products/123456':
                raise RuntimeError('Проверка сохранения ссылки не прошла')
        finally:
            wb.close()
        # Проверяем и полный пошаговый экран из установленного exe.
        from PySide6.QtCore import QSettings
        from desktop_app import MainWindow
        settings = QSettings(str(root / 'wizard.ini'), QSettings.IniFormat)
        settings.setValue('rootDirectory', str(root))
        window = MainWindow(settings=settings)
        window.set_source(path)
        if not window.wizard.go(1):
            raise RuntimeError('Не удалось перейти к нашим ценам')
        grid = window.wizard.preview.grid
        grid.item(0, grid.columnCount() - 1).setText('175')
        if not window.wizard.go(2):
            raise RuntimeError(window.wizard.preview.status.text())
        wb = openpyxl.load_workbook(window.source)
        try:
            if wb.active['C3'].value != 175:
                raise RuntimeError('Пошаговый интерфейс не сохранил НОСИМО')
        finally:
            wb.close()
        window.close()
    return app
