from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
import openpyxl

from result_quality import save_report, cell_status, read_report, failure_message, retry_pairs
from workbook_preview import preview, apply_prices


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'tv.xlsx'
        w=openpyxl.Workbook();w.active.append(['Артикул','Мвидео','DNS','Ozon','Wildberries','НОСИМО'])
        w.active.append([None]);w.active.append(['A',80,90,95,99,100]);w.active.append(['B',120,125,130,140,150]);w.save(self.path)
        self.now=datetime.now(timezone.utc).astimezone()

    def report(self,records):
        return save_report(self.path,'ТВ','all',self.path,records)

    def entry(self,article='A',store='mvideo',status='ok',value=80,at=None):
        return dict(article=article,store=store,status=status,value=value,checkedAt=(at or self.now).isoformat(),note='timeout' if status=='error' else '')

    def test_old_workbook_is_not_fresh_and_does_not_count_cheaper(self):
        data=preview(self.path,stores=['mvideo'])
        self.assertEqual(data['rows'][0]['statuses'][0]['code'],'unchecked')
        self.assertEqual(data['summary']['cheaper'],0)

    def test_fresh_summary_ignores_stale_cheap_prices_and_zero_base(self):
        self.report([self.entry(), self.entry('B',value=120,at=self.now-timedelta(days=1))])
        data=preview(self.path,stores=['mvideo'])
        self.assertEqual(data['summary']['cheaper'],1)
        self.assertEqual(data['summary']['updated'],1)
        self.assertEqual(data['summary']['maxDifference'],20)
        self.assertEqual(data['rows'][1]['statuses'][0]['code'],'stale')
        edited=apply_prices(self.path,data['fingerprint'],[{'row':3,'value':'0'}],stores=['mvideo'])
        self.assertEqual(edited['summary']['cheaper'],0)
        self.assertEqual(edited['rows'][0]['statuses'][0]['code'],'fresh')

    def test_error_keeps_price_but_never_counts_it_as_fresh(self):
        self.report([self.entry(status='error')])
        data=preview(self.path,stores=['mvideo'])
        self.assertIn('80',data['rows'][0]['prices'][0])
        self.assertEqual(data['summary']['errors'],1)
        self.assertEqual(data['summary']['cheaper'],0)
        self.assertEqual(len(data['retryPairs']),1)

    def test_external_price_change_invalidates_status_and_row_reorder_is_safe(self):
        self.report([self.entry()])
        w=openpyxl.load_workbook(self.path);w.active['B3']=70;w.save(self.path)
        self.assertEqual(preview(self.path,stores=['mvideo'])['rows'][0]['statuses'][0]['code'],'unchecked')
        w.active['B3']=80
        a=list(w.active.values)[2];b=list(w.active.values)[3]
        for i,v in enumerate(b,1):w.active.cell(3,i,v)
        for i,v in enumerate(a,1):w.active.cell(4,i,v)
        w.save(self.path);w.close()
        self.assertEqual(preview(self.path,stores=['mvideo'])['rows'][1]['statuses'][0]['code'],'fresh')

    def test_retry_is_bound_to_source_template_and_exact_pairs(self):
        self.report([self.entry(status='error'),self.entry('B','dns','error',125),self.entry('B','mvideo','ok',120)])
        pairs=retry_pairs(self.path,self.path,'all')
        self.assertEqual(pairs,{('ТВ','A','mvideo'),('ТВ','B','dns')})
        with self.assertRaises(ValueError):retry_pairs(self.path,self.path,'tv-spb')
        with self.assertRaises(ValueError):retry_pairs(self.path,self.path.with_name('other.xlsx'),'all')

    def test_corrupt_report_fails_closed(self):
        self.path.with_suffix('.xlsx.monitoring.json').write_text('{bad')
        self.assertEqual(read_report(self.path),{})
        self.assertEqual(preview(self.path)['summary']['updated'],0)
        with self.assertRaises(ValueError):retry_pairs(self.path,self.path,'all')

    def test_human_errors_have_actions(self):
        for text in ['PermissionError: access denied','неверный регион samsungstore: msk','TimeoutError','ссылка на другой товар','RuntimeError: unusual failure']:
            message=failure_message(text)
            self.assertTrue(message['message']);self.assertTrue(message['action'])

    def test_changed_result_is_rejected_before_retry(self):
        self.report([self.entry(status='error')])
        w=openpyxl.load_workbook(self.path);w.active['B3']=79;w.save(self.path);w.close()
        with self.assertRaisesRegex(ValueError,'измен'):retry_pairs(self.path,self.path,'all')

    def test_error_price_is_not_red_in_preview(self):
        self.report([self.entry(status='error')])
        self.assertEqual(preview(self.path,stores=['mvideo'])['rows'][0]['lower'],[False])
        self.report([self.entry()])
        self.assertEqual(preview(self.path,stores=['mvideo'])['rows'][0]['lower'],[True])
