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
