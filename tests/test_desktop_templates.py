"""Проверка настоящих Qt-виджетов с временными настройками и файлами."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
import openpyxl
import desktop_app


class DesktopTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_switch_preserves_legacy_selection_and_phone_stores(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            settings = QSettings(str(root/'settings.ini'), QSettings.IniFormat)
            settings.setValue('rootDirectory', str(root/'results'))
            settings.setValue('stores/ТВ', ['dns'])
            (root/'results').mkdir()
            tv = root/'tv.xlsx'
            wb = openpyxl.Workbook();wb.active.append(['Артикул','Мвидео','DNS','Ozon','Wildberries','НОСИМО']);wb.save(tv)
            phone = root/'phone.xlsx'
            wb = openpyxl.Workbook();wb.active.append(['Артикул','Наименование','Мвидео','DNS','МТС','samsungstore','НОСИМО']);wb.save(phone)
            with patch.object(desktop_app, 'QSettings', return_value=settings):
                window = desktop_app.MainWindow()
            try:
                window.set_source(tv)
                self.assertEqual(window.active_template(), 'tv-spb')
                self.assertEqual(window.selected_stores(), ['samsungstore'])
                self.assertTrue(window.fill_btn.isHidden())
                window.template_picker.setCurrentIndex(window.template_picker.findData('all'))
                self.assertEqual(window.selected_stores(), ['dns'])
                self.assertEqual(set(window.store_checks), {'mvideo','dns','ozon','wb'})
                window.template_picker.setCurrentIndex(window.template_picker.findData('tv-spb'))
                self.assertEqual(window.selected_stores(), ['samsungstore'])
                window.set_source(phone)
                self.assertEqual(window.active_template(), 'all')
                self.assertEqual(set(window.store_checks), {'mvideo','dns','mts','samsungstore'})
            finally:
                window.close()
