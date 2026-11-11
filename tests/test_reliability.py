import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
import openpyxl

from excel import detect_table, write_table
from stores import Result, StoreError, http_ld


class ExcelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.table = {'first_row': 2, 'article_col': 'A', 'base_col': 'C', 'price_cols': {'mts': 'B'}}

    def book(self, name, rows):
        p = self.root / name
        w = openpyxl.Workbook()
        w.active.append(['Артикул', 'МТС', 'НОСИМО'])
        for row in rows:
            w.active.append(row)
        w.save(p)
        w.close()
        return p

    def values(self, path):
        w = openpyxl.load_workbook(path)
        try:
            return list(w.active.values)
        finally:
            w.close()

    def test_reordered_rows_and_new_articles(self):
        old = self.book('old.xlsx', [('A', 10, 100), ('B', 20, 200)])
        current = self.book('current.xlsx', [('B', None, 250), ('A', None, 150), ('C', None, 300)])
        write_table(self.table, old, old, {(2, 'mts'): Result(777)}, base_src_path=current)
        self.assertEqual(self.values(old)[1:], [('B', 777, 250), ('A', 10, 150), ('C', None, 300)])

    def test_duplicate_articles_rejected(self):
        p = self.book('dup.xlsx', [('A', 1, 10), ('A', 2, 20)])
        with self.assertRaisesRegex(ValueError, 'артикул'):
            write_table(self.table, p, p, {})

    def test_missing_required_header_rejected(self):
        p = self.book('phone.xlsx', [('A', 1, 10)])
        w = openpyxl.load_workbook(p)
        w.active.append([])
        w.active['D1'] = 'Наименование'
        w.save(p)
        with self.assertRaisesRegex(ValueError, 'колон'):
            detect_table(p)

    def test_failed_save_preserves_destination(self):
        p = self.book('safe.xlsx', [('A', 10, 100)])
        before = p.read_bytes()
        def broken_save(wb, target):
            Path(target).write_bytes(b'partial zip')
            raise OSError('disk full')
        with patch('openpyxl.workbook.workbook.Workbook.save', broken_save):
            with self.assertRaises(OSError):
                write_table(self.table, p, p, {(2, 'mts'): Result(99)})
        self.assertEqual(p.read_bytes(), before)


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_model_rejected(self):
        product = {'@type': 'Product', 'name': 'Samsung Galaxy S26 Ultra 512GB',
                   'offers': {'@type': 'Offer', 'price': 99999}}
        html = '<script type="application/ld+json">' + json.dumps(product) + '</script>'
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html))) as c:
            with self.assertRaisesRegex(StoreError, 'другой товар'):
                await http_ld(c, 'https://example.test', article='A', model='S26 256GB')


class RunFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_task_crash_saves_collected_data_and_fails_run(self):
        import argparse
        from contextlib import asynccontextmanager
        from unittest.mock import AsyncMock
        import run
        from config import TABLES
        from monitoring_templates import apply_template

        @asynccontextmanager
        async def no_browser():
            yield None

        async def crashed_task(store, items, page, http, results, log, progress, **options):
            results['ТВ'][(3, 'samsungstore')] = Result(80, 'https://example.test', 'Санкт-Петербург')
            raise RuntimeError('unexpected crash')

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root/'tv.xlsx'
            w = openpyxl.Workbook()
            w.active.append(['Артикул','Мвидео','DNS','Ozon','Wildberries','НОСИМО'])
            w.active.append([None])
            w.active.append(['A',None,None,None,None,100])
            w.save(source)
            table = apply_template(dict(TABLES[0], file=str(source), base_col='F'), 'tv-spb')
            args = argparse.Namespace(root=str(root/'out'), file=str(source), template='tv-spb',
                tables=None, stores=None, articles=None, limit=None, no_links_refresh=False,
                links=None, legacy_links=None, stop_file=None, out=None)
            with patch.object(run, 'selected_tables', return_value=[table]), \
                 patch.object(run, 'async_playwright', no_browser), \
                 patch.object(run, 'run_store', crashed_task), \
                 patch.object(run, 'screenshot', new=AsyncMock()), \
                 patch.object(run, 'load_links', side_effect=AssertionError('SPB must not touch links')):
                with self.assertRaisesRegex(RuntimeError, 'unexpected crash'):
                    await run.main(args)
            reports = list((root/'out').rglob('*СПБ.xlsx'))
            self.assertEqual(len(reports), 1)
            w = openpyxl.load_workbook(reports[0])
            self.assertEqual(w.active['B3'].value, 80)
            w.close()


class TableDetectionTests(unittest.TestCase):
    def test_phone_with_dotted_mvideo_header_is_not_tv(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'phones.xlsx'
            w=openpyxl.Workbook()
            w.active.append(['Артикул','Наименование','М.Видео','DNS','МТС','samsungstore','НОСИМО'])
            w.save(path)
            t=detect_table(path)
            self.assertEqual(t['name'],'Смартфоны')
            self.assertEqual(t['first_row'],2)
            self.assertEqual(set(t['price_cols']),{'mvideo','dns','mts','samsungstore'})
