import argparse
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
import openpyxl
from excel import detect_table
from monitoring_templates import apply_template
from result_quality import save_report, read_report
import run


class RetryQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.source=self.root/'tv.xlsx';w=openpyxl.Workbook();w.active.append(['Артикул','Мвидео','DNS','Ozon','Wildberries','НОСИМО']);w.active.append([None]);w.active.append(['A',80,90,95,99,100]);w.active.append(['B',120,125,130,140,150]);w.save(self.source)
        self.table=apply_template(detect_table(self.source),'all')
        self.args=argparse.Namespace(file=str(self.source),template='all',articles=None,limit=None,stores=['mvideo','dns'],retry_report=None)
        self.records=[dict(article='A',store='mvideo',status='error',value=80,note='timeout'),dict(article='B',store='dns',status='error',value=125,note='timeout')]
        save_report(self.source,'ТВ','all',self.source,self.records)
        self.links={('ТВ',a):{'mvideo':'https://example.test/'+a,'dns':'https://example.test/'+a} for a in ['A','B']}

    def test_retry_filters_exact_pairs_not_cross_product(self):
        self.args.retry_report=str(self.source)
        jobs=run.build_jobs(self.args,self.links,[self.table])
        self.assertEqual({(s,item[2]) for s,items in jobs.items() for item in items},{('mvideo','A'),('dns','B')})

    def test_unknown_article_in_manifest_is_rejected_before_network(self):
        self.args.retry_report=str(self.source);self.records[0]['article']='OTHER'
        save_report(self.source,'ТВ','all',self.source,self.records)
        with self.assertRaisesRegex(ValueError,'артикул'):run.build_jobs(self.args,self.links,[self.table])

    def test_report_marks_unprocessed_and_keeps_successful_checks(self):
        from result_quality import write_run_report
        jobs={'mvideo':[('ТВ',3,'A',None,100,None),('ТВ',4,'B',None,150,None)]}
        outcomes={('ТВ','A','mvideo'):dict(status='ok',note='',checkedAt=datetime.now().astimezone().isoformat())}
        write_run_report(self.table,self.source,self.source,jobs,outcomes)
        data=read_report(self.source);records={(r['article'],r['store']):r for r in data['records']}
        self.assertEqual(records['A','mvideo']['status'],'ok')
        self.assertEqual(records['B','mvideo']['status'],'pending')
        self.assertEqual(records['B','dns']['status'],'error')

    def test_retry_next_day_can_seed_spb_prices_without_changing_design(self):
        from tv_report import write_report
        from stores import Result
        table=apply_template(detect_table(self.source),'tv-spb')
        old=self.root/'old.xlsx';new=self.root/'new.xlsx'
        write_report(table,self.source,old,{(3,'samsungstore'):Result(77),(4,'samsungstore'):Result(88)})
        write_report(table,self.source,new,{(3,'samsungstore'):Result(66)},previous_source=old)
        w=openpyxl.load_workbook(new)
        self.assertEqual([w.active['B3'].value,w.active['B4'].value],[66,88]);self.assertEqual(w.active.max_column,3);w.close()

class AllFailuresTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_store_errors_replace_previous_fresh_status(self):
        import shutil
        from contextlib import asynccontextmanager
        from datetime import datetime
        import layout
        from workbook_preview import preview
        @asynccontextmanager
        async def no_browser():yield None
        async def fail_all(store,items,*args,**kwargs):
            for item in items:
                kwargs['outcomes'][item[0],item[2],store]=dict(status='error',note='timeout',checkedAt=datetime.now().astimezone().isoformat())
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'tv.xlsx'
            w=openpyxl.Workbook();w.active.append(['Артикул','Мвидео','DNS','Ozon','Wildberries','НОСИМО']);w.active.append([None]);w.active.append(['A',80,90,95,99,100]);w.save(source)
            table=apply_template(detect_table(source),'all');destination=layout.table_dir(root/'out','ТВ')/source.name
            destination.parent.mkdir(parents=True);shutil.copy2(source,destination)
            save_report(destination,'ТВ','all',source,[dict(article='A',store='mvideo',status='ok',value=80,note='',checkedAt=datetime.now().astimezone().isoformat())])
            args=argparse.Namespace(file=str(source),root=str(root/'out'),out=None,template='all',tables=None,stores=['mvideo'],articles=None,limit=None,no_links_refresh=True,retry_report=None,links=None,legacy_links=None,stop_file=None)
            jobs={'mvideo':[('ТВ',3,'A','https://example.test',100,None)]}
            with patch.object(run,'selected_tables',return_value=[table]),patch.object(run,'build_jobs',return_value=jobs),patch.object(run,'load_all_links',return_value={}),patch.object(run,'STORE_IMPL',{'mvideo':(None,False,'link')}),patch.object(run,'async_playwright',no_browser),patch.object(run,'run_store',fail_all),patch.object(run,'screenshot',new=AsyncMock()):
                await run.main(args)
            data=preview(destination,stores=['mvideo'])
            self.assertEqual(data['rows'][0]['statuses'][0]['code'],'error')
            self.assertEqual(len(data['retryPairs']),1)

    async def test_missing_links_are_pending_and_do_not_open_browser(self):
        from contextlib import asynccontextmanager
        from workbook_preview import preview
        import layout
        class BrowserMustNotStart:
            async def launch_persistent_context(self,*args,**kwargs):raise AssertionError('No browser for missing links')
        @asynccontextmanager
        async def playwright_stub():yield argparse.Namespace(chromium=BrowserMustNotStart())
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'tv.xlsx'
            w=openpyxl.Workbook();w.active.append(['Артикул','Мвидео','DNS','Ozon','Wildberries','НОСИМО']);w.active.append([None]);w.active.append(['A',80,90,95,99,100]);w.save(source)
            table=apply_template(detect_table(source),'all')
            save_report(source,'ТВ','all',source,[dict(article='A',store='mvideo',status='ok',value=80,note='',checkedAt=datetime.now().astimezone().isoformat())])
            args=argparse.Namespace(file=str(source),root=str(root/'out'),out=None,template='all',tables=None,stores=['mvideo'],articles=None,limit=None,no_links_refresh=True,retry_report=None,links=None,legacy_links=None,stop_file=None)
            with patch.object(run,'selected_tables',return_value=[table]),patch.object(run,'load_all_links',return_value={}),patch.object(run,'async_playwright',playwright_stub),patch.object(run,'screenshot',new=AsyncMock()):
                await run.main(args)
            dest=layout.table_dir(root/'out','ТВ')/source.name
            self.assertTrue(dest.exists())
            self.assertEqual(preview(dest,stores=['mvideo'])['rows'][0]['statuses'][0]['code'],'pending')

class ShiftedColumnTests(unittest.TestCase):
    def test_spb_status_uses_destination_columns(self):
        from tv_report import write_report
        from stores import Result
        from result_quality import write_run_report
        from workbook_preview import preview
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.xlsx';dest=Path(folder)/'dest.xlsx'
            w=openpyxl.Workbook();w.active['B1']='Артикул';w.active['D1']='Мвидео';w.active['H1']='НОСИМО';w.active['B3']='A';w.active['H3']=100
            w.active['E1']='DNS';w.active['F1']='Ozon';w.active['G1']='Wildberries';w.save(source)
            t=apply_template(detect_table(source),'tv-spb');write_report(t,source,dest,{(3,'samsungstore'):Result(80)})
            write_run_report(t,source,dest,{'samsungstore':[('ТВ',3,'A',None,100,None)]},{('ТВ','A','samsungstore'):dict(status='ok',note='',checkedAt=datetime.now().astimezone().isoformat())})
            self.assertEqual(preview(dest,'tv-spb')['rows'][0]['statuses'][0]['code'],'fresh')
