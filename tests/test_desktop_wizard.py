import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import openpyxl
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLineEdit
import desktop_app


class WizardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        settings=QSettings(str(self.root/'settings.ini'),QSettings.IniFormat);settings.setValue('rootDirectory',str(self.root))
        with patch.object(desktop_app,'QSettings',return_value=settings):self.window=desktop_app.MainWindow()
        self.addCleanup(self.window.close)
        self.file=self.root/'tv.xlsx';w=openpyxl.Workbook();w.active.append(['Артикул','Розничная цена samsungstore СПБ','НОСИМО']);w.active.append([None]);w.active.append(['A',80,100]);w.save(self.file)

    def test_no_file_cannot_skip_to_collection(self):
        self.assertFalse(self.window.wizard.go(2));self.assertEqual(self.window.wizard.step,0)
        self.assertFalse(self.window.start_btn.isEnabled())

    def test_next_saves_active_price_editor_before_advancing(self):
        w=self.window;w.set_source(self.file);w.show();self.app.processEvents()
        self.assertTrue(w.wizard.go(1));grid=w.wizard.preview.grid
        grid.setCurrentCell(0,2);grid.editItem(grid.item(0,2));self.app.processEvents()
        editor=grid.findChild(QLineEdit);self.assertIsNotNone(editor);editor.setText('150')
        self.assertTrue(w.wizard.go(2));self.assertEqual(w.wizard.step,2)
        book=openpyxl.load_workbook(w.source);self.assertEqual(book.active['C3'].value,150);book.close()

    def test_busy_locks_navigation_and_prices(self):
        w=self.window;w.set_source(self.file);w.phase='running';w.refresh()
        self.assertEqual(w.wizard.step,2);self.assertFalse(w.wizard.go(0))
        self.assertFalse(w.wizard.back.isEnabled());self.assertFalse(w.wizard.preview.editable)
        self.assertEqual(w.start_btn.text(),'Остановить')
        w.phase='finished';w.refresh();self.assertTrue(w.wizard.go(1))

    def test_stale_file_stops_transition_without_losing_pending_price(self):
        w=self.window;w.set_source(self.file);w.wizard.go(1)
        w.wizard.preview.grid.item(0,2).setText('150')
        book=openpyxl.load_workbook(w.source);book.active['C3']=777;book.save(w.source);book.close()
        self.assertFalse(w.wizard.go(2));self.assertEqual(w.wizard.step,1)
        self.assertTrue(w.wizard.preview.pending)
        self.assertTrue(w.wizard.preview.discard(confirm=False))
        self.assertFalse(w.wizard.preview.pending)
        self.assertTrue(w.wizard.go(2))
        book=openpyxl.load_workbook(w.source);self.assertEqual(book.active['C3'].value,777);book.close()
