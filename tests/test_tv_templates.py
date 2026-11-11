import json
import unittest
from pathlib import Path
import tempfile

import httpx
import openpyxl

from stores import StoreError, Result
from samsung_tv import SamsungTV
from monitoring_templates import apply_template
from tv_report import write_report
from config import TABLES


def page(data, region='spb'):
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({
        'props': {'props': {'currentRegion': {'REGION_CODE': region}}, 'pageProps': data}}) + '</script>'


def catalog(items, current=1, last=1):
    return page({'initialState': {'api': {'queries': {'products': {
        'endpointName': 'getProducts', 'status': 'fulfilled',
        'originalArgs': {'params': {'page': str(current)}, 'regionCookies': 'CITY_CODE=spb'},
        'data': {'TOTAL': len(items) * last, 'CURRENT_PAGE': current, 'LAST_PAGE': last, 'ITEMS': items}}}}}})


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_spb_exact_article_and_pagination(self):
        seen = []
        def respond(r):
            seen.append(r)
            if r.url.path.startswith('/catalog/'):
                n = int(r.url.params.get('page', '1'))
                return httpx.Response(200, text=catalog([{'KOD': str(n)}], n, 2))
            art = 'QE43LS03FAUXRU' if '1' in r.url.path else 'QE43LS03FAUXCE'
            return httpx.Response(200, text=page({'product': {'ARTICLE': art, 'TITLE': 'Телевизор',
                'PRICE': {'VALUE': 69990, 'PRICE_TYPE': 'spb_special'}, 'ORDER_TYPE': 'ORDER', 'VISIBLE_PRICE': True}}))
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as c:
            site = SamsungTV(c)
            res = await site.find('QE43LS03FAUXRU')
            self.assertEqual(res.price, 69990)
            self.assertIn('productID1', res.url)
            self.assertTrue(all('CITY_CODE=spb' in r.headers.get('cookie', '') for r in seen))
            self.assertTrue(any(r.url.params.get('page') == '2' for r in seen))

    async def test_wrong_region_is_error(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda r: httpx.Response(200, text=page({}, region='msk')))) as c:
            with self.assertRaisesRegex(StoreError, 'регион'):
                await SamsungTV(c).find('UE32H5000FUXRU')

    async def test_broken_catalog_is_error_not_absence(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda r: httpx.Response(200, text=page({})))) as c:
            with self.assertRaises(StoreError):
                await SamsungTV(c).find('UE32H5000FUXRU')

    async def test_moscow_price_rejected(self):
        def respond(r):
            data = catalog([{'KOD': '1'}]) if '/catalog/' in r.url.path else page({'product': {
                'ARTICLE': 'A', 'PRICE': {'VALUE': 99, 'PRICE_TYPE': 'msk_special'}, 'ORDER_TYPE': 'ORDER', 'VISIBLE_PRICE': True}})
            return httpx.Response(200, text=data)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as c:
            with self.assertRaisesRegex(StoreError, 'цен'):
                await SamsungTV(c).find('A')


class TemplateTests(unittest.TestCase):
    def test_legacy_stores_unchanged(self):
        self.assertEqual(set(apply_template(TABLES[0], 'all')['price_cols']), {'mvideo', 'dns', 'ozon', 'wb'})
        self.assertEqual(set(TABLES[0]['price_cols']), {'mvideo', 'dns', 'ozon', 'wb'})

    def test_spb_only_for_tv(self):
        self.assertEqual(set(apply_template(TABLES[0], 'tv-spb')['price_cols']), {'samsungstore'})
        with self.assertRaises(ValueError):
            apply_template(TABLES[1], 'tv-spb')

    def test_report_preserves_old_price_by_article_on_error(self):
        with tempfile.TemporaryDirectory() as d:
            source, out = Path(d)/'source.xlsx', Path(d)/'report.xlsx'
            t = dict(TABLES[0], first_row=2, article_col='A', base_col='C', price_cols={'samsungstore':'B'})
            w = openpyxl.Workbook(); w.active.append(['Артикул','Мвидео','НОСИМО']);w.active.append(['A',90,100]);w.active.append(['B',190,200]);w.save(source)
            write_report(t,source,out,{(2,'samsungstore'):Result(80,'https://example.test','СПБ')})
            w = openpyxl.load_workbook(source); w.active['A2']='B';w.active['C2']=200;w.active['A3']='A';w.active['C3']=100;w.save(source)
            write_report(t,source,out,{(2,'samsungstore'):Result(None,'','нет в каталоге')})
            w=openpyxl.load_workbook(out);rows=list(w.active.values)
            self.assertEqual(rows[1][0],'B');self.assertEqual(rows[1][1],'-')
            self.assertEqual(rows[2][0],'A');self.assertEqual(rows[2][1],80)
            w.close()

    def test_preserves_workbook_layout_styles_and_formulas(self):
        from copy import copy
        from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
        with tempfile.TemporaryDirectory() as d:
            src,out=Path(d)/'source.xlsx',Path(d)/'out.xlsx'
            w=openpyxl.Workbook();ws=w.active;ws.title='Исходный шаблон'
            ws.append(['Артикул','Мвидео','НОСИМО','DNS']);ws.append(['A',110,'=100',999])
            ws['B1'].font=Font(name='Arial',size=16,bold=True,color='FF123456')
            ws['B2'].font=Font(name='Calibri',size=13,italic=True)
            ws['B2'].fill=PatternFill('solid',fgColor='FFBBCCDD')
            ws['B2'].border=Border(bottom=Side(style='thick',color='FF334455'))
            ws['B2'].alignment=Alignment(horizontal='right')
            ws['B2'].number_format='#,##0.00 ₽'
            ws.column_dimensions['B'].width=31;ws.row_dimensions[2].height=34
            ws.merge_cells('E1:F1');ws['E1']='Примечания';ws.freeze_panes='B2'
            ws.sheet_view.view='pageBreakPreview';ws.print_area='A1:F2'
            w.create_sheet('Служебный')['A1']='=1+1';w['Служебный']['B1']="='Исходный шаблон'!C2";w.save(src)
            t=dict(TABLES[0],first_row=2,article_col='A',base_col='C',price_cols={'samsungstore':'B'})
            write_report(t,src,out,{(2,'samsungstore'):Result(120,'https://example.test','СПБ')})
            result=openpyxl.load_workbook(out);rs=result.active
            self.assertEqual(result.sheetnames,w.sheetnames)
            self.assertEqual(rs.max_column,3)
            self.assertEqual(rs['B1'].value,'Розничная цена samsungstore СПБ')
            original=openpyxl.load_workbook(src)
            for row in original.active.iter_rows(max_col=3):
                for c in row:
                    self.assertEqual(rs[c.coordinate]._style,c._style,c.coordinate)
                    if c.coordinate not in ('B1','B2'):self.assertEqual(rs[c.coordinate].value,c.value)
            self.assertEqual(rs['C2'].value,'=100')
            self.assertEqual(rs.column_dimensions['B'].width,31)
            self.assertEqual(rs.row_dimensions[2].height,34)
            self.assertEqual(str(rs.merged_cells),'')
            self.assertEqual(rs.freeze_panes,ws.freeze_panes)
            self.assertEqual(rs.sheet_view.view,ws.sheet_view.view)
            self.assertEqual(str(rs.print_area),"'Исходный шаблон'!$A$1:$C$2")
            self.assertEqual(result['Служебный']['A1'].value,'=1+1')
            self.assertEqual(result['Служебный']['B1'].value,"='Исходный шаблон'!C2")
            result.close();w.close();original.close()

    def test_comparison_still_highlights_lower_price(self):
        from excel import is_red
        with tempfile.TemporaryDirectory() as d:
            src,out=Path(d)/'source.xlsx',Path(d)/'out.xlsx'
            w=openpyxl.Workbook();w.active.append(['Артикул','Мвидео','НОСИМО']);w.active.append(['A',110,100]);w.save(src)
            t=dict(TABLES[0],first_row=2,article_col='A',base_col='C',price_cols={'samsungstore':'B'})
            write_report(t,src,out,{(2,'samsungstore'):Result(80)})
            result=openpyxl.load_workbook(out)
            self.assertTrue(is_red(result.active['B2']))
            result.close()

    def test_spb_output_can_be_selected_for_next_run(self):
        from excel import detect_table
        with tempfile.TemporaryDirectory() as d:
            src,out=Path(d)/'source.xlsx',Path(d)/'out.xlsx'
            w=openpyxl.Workbook();w.active.append(['Артикул','Мвидео','DNS','Ozon','Wildberries','НОСИМО']);w.active.append([None]);w.active.append(['A',110,99,99,99,100]);w.save(src)
            table=apply_template(detect_table(src),'tv-spb')
            write_report(table,src,out,{(3,'samsungstore'):Result(80)})
            detected=apply_template(detect_table(out))
            self.assertEqual(detected['template'],'tv-spb')
            self.assertEqual(detected['base_col'],'C')
            self.assertEqual(detected['price_cols'],{'samsungstore':'B'})
            write_report(detected,out,Path(d)/'next.xlsx',{(3,'samsungstore'):Result(90)})
            result=openpyxl.load_workbook(Path(d)/'next.xlsx')
            self.assertEqual(result.active['B3'].value,90)
            self.assertEqual(result.active['C3'].value,100)
            self.assertEqual(result.active.max_column,3)
            result.close()

    def test_first_spb_run_does_not_relabel_old_mvideo_prices(self):
        from excel import detect_table
        with tempfile.TemporaryDirectory() as d:
            src,out=Path(d)/'source.xlsx',Path(d)/'out.xlsx'
            w=openpyxl.Workbook();w.active.append(['Артикул','Мвидео','DNS','Ozon','Wildberries','НОСИМО']);w.active.append([None]);w.active.append(['A',110,99,99,99,100]);w.save(src)
            table=apply_template(detect_table(src),'tv-spb')
            write_report(table,src,out,{})
            result=openpyxl.load_workbook(out)
            self.assertIsNone(result.active['B3'].value)
            self.assertEqual(result.active['C3'].value,100)
            result.close()

    def test_rewrites_other_sheet_reference_to_moved_base_column(self):
        with tempfile.TemporaryDirectory() as d:
            src,out=Path(d)/'source.xlsx',Path(d)/'out.xlsx'
            w=openpyxl.Workbook();w.active.title='ТВ';w.active.append(['Артикул','Мвидео','DNS','НОСИМО']);w.active.append(['A',110,99,100])
            w.create_sheet('Служебный')['A1']="='ТВ'!D2";w['Служебный']['A2']='=D2';w.save(src)
            t=dict(TABLES[0],first_row=2,article_col='A',base_col='D',price_cols={'samsungstore':'B'})
            write_report(t,src,out,{(2,'samsungstore'):Result(120)})
            result=openpyxl.load_workbook(out)
            self.assertEqual(result['Служебный']['A1'].value,"='ТВ'!C2")
            self.assertEqual(result['Служебный']['A2'].value,'=D2')
            result.close()
