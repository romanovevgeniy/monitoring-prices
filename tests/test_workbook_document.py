from pathlib import Path
import tempfile
import unittest

import openpyxl
from openpyxl.styles import Font, PatternFill

from workbook_document import WorkbookDocument


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'tv.xlsx'
        w=openpyxl.Workbook();s=w.active
        s.append(['Артикул','Розничная цена samsungstore СПБ','Розничная цена НОСИМО']);s.append([None]);s.append(['A',80,100])
        s['C3'].font=Font(name='Arial',size=14,bold=True)
        s['C3'].number_format='#,##0.00 ₽'
        s['C3'].fill=PatternFill('solid',fgColor='FFABCDEF')
        s.column_dimensions['C'].width=29;s.row_dimensions[3].height=27
        s.merge_cells('A1:A2');w.save(self.path)

    def document(self,mode='prices',editable=True):
        doc=WorkbookDocument(self.path,mode=mode,editable=editable)
        self.addCleanup(doc.close)
        return doc

    def test_edit_base_preserves_style_and_creates_backup(self):
        before=self.path.read_bytes();doc=self.document();sheet=doc.workbook.active.title
        doc.set_value(sheet,3,3,'72 990,50 ₽')
        backup=doc.save()
        self.assertEqual(backup.read_bytes(),before)
        w=openpyxl.load_workbook(self.path);s=w.active
        self.assertEqual(s['C3'].value,72990.5)
        self.assertEqual(s['C3'].font.name,'Arial');self.assertTrue(s['C3'].font.bold)
        self.assertEqual(s['C3'].fill.fgColor.rgb,'FFABCDEF')
        self.assertEqual(s['C3'].number_format,'#,##0.00 ₽')
        self.assertEqual(s.column_dimensions['C'].width,29)
        self.assertEqual(str(s.merged_cells),'A1:A2');w.close()

    def test_protected_cells_and_invalid_prices(self):
        doc=self.document();sheet=doc.workbook.active.title
        with self.assertRaises(ValueError):doc.set_value(sheet,3,2,'90')
        for value in ('=1+1','-50','NaN','1e100','text','99,999'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):doc.set_value(sheet,3,3,value)
        self.assertFalse(doc.dirty)

    def test_external_change_is_not_overwritten(self):
        doc=self.document();doc.set_value(doc.workbook.active.title,3,3,'120')
        w=openpyxl.load_workbook(self.path);w.active['B3']=777;w.save(self.path)
        with self.assertRaisesRegex(ValueError,'измен'):
            doc.save()
        w=openpyxl.load_workbook(self.path);self.assertEqual(w.active['B3'].value,777);w.close()

    def test_readonly_and_empty_price(self):
        doc=self.document(editable=False)
        with self.assertRaises(ValueError):doc.set_value(doc.workbook.active.title,3,3,'120')
        self.assertFalse(doc.dirty)
        editable=self.document();editable.set_value(editable.workbook.active.title,3,3,'')
        editable.save();w=openpyxl.load_workbook(self.path);self.assertIsNone(w.active['C3'].value);w.close()

    def test_links_only_allow_url_columns_and_safe_schemes(self):
        path=Path(self.tmp.name)/'links.xlsx';w=openpyxl.Workbook();w.active.title='ТВ'
        w.active.append(['Артикул','Наименование','М.Видео','DNS']);w.active.append(['A','TV',None,None]);w.save(path)
        doc=WorkbookDocument(path,mode='links');self.addCleanup(doc.close)
        for value in ('=HYPERLINK("bad")','javascript:alert(1)','https://','file:///tmp/x'):
            with self.assertRaises(ValueError):doc.set_value('ТВ',2,3,value)
        with self.assertRaises(ValueError):doc.set_value('ТВ',2,1,'B')
        doc.set_value('ТВ',2,3,'https://www.mvideo.ru/products/123456')
        doc.set_value('ТВ',2,4,'-');doc.save()
        w=openpyxl.load_workbook(path);self.assertEqual(w.active['D2'].value,'-');w.close()

    def test_link_metadata_follows_edited_value_and_clearing(self):
        path=Path(self.tmp.name)/'links.xlsx';w=openpyxl.Workbook();w.active.title='ТВ'
        w.active.append(['Артикул','Наименование','М.Видео']);w.active.append(['A','TV','https://old.test'])
        w.active['C2'].hyperlink='https://old.test';w.save(path)
        doc=WorkbookDocument(path,mode='links');self.addCleanup(doc.close)
        doc.set_value('ТВ',2,3,'https://new.test');doc.save()
        w=openpyxl.load_workbook(path);self.assertEqual(w.active['C2'].hyperlink.target,'https://new.test');w.close()
        doc.set_value('ТВ',2,3,'-');doc.save()
        w=openpyxl.load_workbook(path);self.assertIsNone(w.active['C2'].hyperlink);w.close()
