from pathlib import Path
import tempfile
import unittest

import openpyxl

from workbook_preview import preview, apply_prices


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'tv.xlsx'
        w=openpyxl.Workbook();w.active.append(['Артикул','Мвидео','DNS','Ozon','Wildberries','НОСИМО'])
        w.active.append([None]);w.active.append(['A',80,90,95,99,100]);w.active.append(['B',120,125,130,140,150]);w.save(self.path)

    def test_spb_does_not_show_mvideo_as_samsungstore(self):
        data=preview(self.path,'tv-spb')
        self.assertEqual(data['columns'][0]['key'],'samsungstore')
        self.assertEqual(data['rows'][0]['prices'],['—'])
        self.assertEqual(data['rows'][0]['base'],'100')
        self.assertEqual(data['count'],2)

    def test_all_stores_and_filter(self):
        data=preview(self.path,'all',stores=['dns'])
        self.assertEqual([c['key'] for c in data['columns']],['dns'])
        self.assertEqual(data['rows'][0]['lower'],[True])
        self.assertIn('90',data['rows'][0]['prices'][0])

    def test_save_multiple_changes_with_original_layout(self):
        original=preview(self.path)
        data=apply_prices(self.path,original['fingerprint'],[{'row':3,'value':'110'},{'row':4,'value':'160'}])
        self.assertEqual([r['base'] for r in data['rows']],['110','160'])
        self.assertNotEqual(data['fingerprint'],original['fingerprint'])
        w=openpyxl.load_workbook(self.path);self.assertEqual(w.active.max_column,6);w.close()
        self.assertEqual(len(list((self.path.parent/'Резервные копии таблиц').glob('*.xlsx'))),1)

    def test_bad_second_edit_does_not_save_first_edit(self):
        before=self.path.read_bytes();data=preview(self.path)
        with self.assertRaises(ValueError):
            apply_prices(self.path,data['fingerprint'],[{'row':3,'value':'110'},{'row':4,'value':'=1+1'}])
        self.assertEqual(self.path.read_bytes(),before)

    def test_stale_fingerprint_rejected(self):
        data=preview(self.path);w=openpyxl.load_workbook(self.path);w.active['F3']=222;w.save(self.path)
        with self.assertRaisesRegex(ValueError,'измен'):
            apply_prices(self.path,data['fingerprint'],[{'row':3,'value':'110'}])
