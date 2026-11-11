import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import openpyxl
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from workbook_editor import WorkbookEditor


class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_edit_save_without_external_excel_and_validation(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'prices.xlsx';w=openpyxl.Workbook()
            w.active.append(['Артикул','Розничная цена samsungstore СПБ','НОСИМО']);w.active.append([None]);w.active.append(['A',80,100]);w.save(path)
            dialog=WorkbookEditor(path)
            grid=dialog.current_grid()
            self.assertFalse(grid.item(2,1).flags() & Qt.ItemIsEditable)
            self.assertTrue(grid.item(2,2).flags() & Qt.ItemIsEditable)
            grid.item(2,2).setText('150')
            self.assertTrue(dialog.document.dirty)
            self.assertTrue(dialog.save_document())
            w=openpyxl.load_workbook(path);self.assertEqual(w.active['C3'].value,150);w.close()
            grid=dialog.current_grid();grid.item(2,2).setText('=bad')
            self.assertFalse(dialog.document.dirty)
            self.assertIn('Цена',dialog.status.text())
            dialog.reject()

    def test_merged_cells_and_readonly(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'prices.xlsx';w=openpyxl.Workbook()
            w.active.append(['Артикул','Розничная цена samsungstore СПБ','НОСИМО']);w.active.append([None]);w.active.append(['A',80,100])
            w.active.merge_cells('A1:A2');w.save(path)
            dialog=WorkbookEditor(path,editable=False)
            grid=dialog.current_grid()
            self.assertEqual(grid.rowSpan(0,0),2)
            self.assertFalse(grid.item(2,2).flags() & Qt.ItemIsEditable)
            self.assertFalse(dialog.save_button.isEnabled())
            dialog.reject()

    def test_ui_save_keeps_column_and_row_dimensions(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'prices.xlsx';w=openpyxl.Workbook()
            w.active.append(['Артикул','Розничная цена samsungstore СПБ','НОСИМО']);w.active.append([None]);w.active.append(['A',80,100])
            w.active.column_dimensions['C'].width=29
            w.active.row_dimensions[3].height=31
            w.save(path)
            original=openpyxl.load_workbook(path)
            columns=set(original.active.column_dimensions);rows=set(original.active.row_dimensions)
            dialog=WorkbookEditor(path)
            dialog.current_grid().item(2,2).setText('120')
            self.assertTrue(dialog.save_document());dialog.reject()
            result=openpyxl.load_workbook(path)
            self.assertEqual(set(result.active.column_dimensions),columns)
            self.assertEqual(set(result.active.row_dimensions),rows)
            self.assertEqual(result.active.column_dimensions['C'].width,29)
            self.assertEqual(result.active.row_dimensions[3].height,31)
            original.close();result.close()

    def test_unsaved_cancel_keeps_dialog_and_changes(self):
        from PySide6.QtWidgets import QMessageBox
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'prices.xlsx';w=openpyxl.Workbook()
            w.active.append(['Артикул','Розничная цена samsungstore СПБ','НОСИМО']);w.active.append([None]);w.active.append(['A',80,100]);w.save(path)
            dialog=WorkbookEditor(path);dialog.show()
            dialog.current_grid().item(2,2).setText('120')
            with patch('workbook_editor.QMessageBox.question',return_value=QMessageBox.Cancel):
                dialog.reject()
            self.assertTrue(dialog.isVisible());self.assertTrue(dialog.document.dirty)
            with patch('workbook_editor.QMessageBox.question',return_value=QMessageBox.Discard):
                dialog.reject()
            w=openpyxl.load_workbook(path);self.assertEqual(w.active['C3'].value,100);w.close()

    def test_ctrl_s_commits_active_cell_editor(self):
        from PySide6.QtGui import QKeySequence
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QLineEdit
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'prices.xlsx';w=openpyxl.Workbook()
            w.active.append(['Артикул','Розничная цена samsungstore СПБ','НОСИМО']);w.active.append([None]);w.active.append(['A',80,100]);w.save(path)
            dialog=WorkbookEditor(path);dialog.show();self.app.processEvents()
            grid=dialog.current_grid();grid.setCurrentCell(2,2);grid.editItem(grid.item(2,2));self.app.processEvents()
            entry=grid.findChild(QLineEdit);self.assertIsNotNone(entry)
            entry.setText('150');self.assertFalse(dialog.document.dirty)
            QTest.keySequence(entry,QKeySequence.Save);self.app.processEvents()
            w=openpyxl.load_workbook(path);self.assertEqual(w.active['C3'].value,150);w.close()
            dialog.reject()
