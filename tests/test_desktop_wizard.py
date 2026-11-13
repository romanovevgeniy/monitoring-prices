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
        self.addCleanup(self.cleanup_window)
        self.file=self.root/'tv.xlsx';w=openpyxl.Workbook();w.active.append(['Артикул','Розничная цена samsungstore СПБ','НОСИМО']);w.active.append([None]);w.active.append(['A',80,100]);w.save(self.file)

    def cleanup_window(self):
        self.window.phase='finished'
        self.window.wizard.preview.pending={}
        self.window.close()

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

    def test_quality_filter_keeps_editing_bound_to_original_row(self):
        from datetime import datetime
        from result_quality import save_report
        w=self.window;w.set_source(self.file)
        book=openpyxl.load_workbook(w.source);book.active.append(['B',70,120]);book.save(w.source);book.close()
        save_report(w.source,'ТВ','tv-spb',w.source,[dict(article='A',store='samsungstore',status='error',value=80,note='timeout'),dict(article='B',store='samsungstore',status='ok',value=70,note='',checkedAt=datetime.now().astimezone().isoformat())])
        w.wizard.reload();p=w.wizard.preview
        p.filter_combo.setCurrentIndex(p.filter_combo.findData('cheaper'))
        self.assertTrue(p.grid.isRowHidden(0));self.assertFalse(p.grid.isRowHidden(1))
        self.assertIn('Ошибка',p.grid.item(0,1).text())
        w.wizard.go(1);p.grid.item(1,2).setText('130');self.assertTrue(p.save())
        book=openpyxl.load_workbook(w.source);self.assertEqual(book.active['C4'].value,130);self.assertEqual(book.active['C3'].value,100);book.close()

    def test_failure_event_survives_process_exit(self):
        import json
        w=self.window;w.set_source(self.file);w.phase='running'
        w.handle('@@'+json.dumps(dict(type='failure',message='Сайт не ответил вовремя.',action='Повторите позже.')))
        w.finish_run(1)
        self.assertIn('Сайт не ответил',w.fail_message);self.assertIn('Повторите позже',w.fail_message)

    def test_retry_launch_uses_saved_result_manifest(self):
        from result_quality import save_report
        w=self.window;w.set_source(self.file)
        save_report(w.source,'ТВ','tv-spb',w.source,[dict(article='A',store='samsungstore',status='error',value=80,note='timeout')])
        w.phase='finished';w.saved=[str(w.source)];w.wizard.go(2);w.wizard.reload()
        with patch.object(w,'launch') as launch:
            w.retry_failed()
        self.assertEqual(launch.call_args.args[0],'run')
        args=launch.call_args.args[1];self.assertEqual(args[args.index('--retry-report')+1],str(w.source))
        w.phase='finished'

    def test_failed_process_start_does_not_leave_window_busy(self):
        from PySide6.QtTest import QTest
        w=self.window;w.set_source(self.file);w.begin('running')
        with patch.object(desktop_app,'tool_command',return_value=('/definitely/missing-monitoring-executable',[])):
            w.launch('run',[],then=w.finish_run)
            for _ in range(10):QTest.qWait(10)
        self.assertFalse(w.busy());self.assertEqual(w.phase,'failed')
        self.assertIn('запуст',w.fail_message.lower())

    def test_skipped_link_is_not_counted_as_out_of_stock(self):
        import json
        w=self.window;w.set_source(self.file)
        w.handle('@@'+json.dumps(dict(type='plan',total=1,stores=[dict(name='Test',total=1)])))
        w.handle('@@'+json.dumps(dict(type='item',store='Test',article='A',status='пропущено',done=1,total=1)))
        row=w.stores['Test']
        self.assertEqual(row.missing,0);self.assertEqual(row.skipped,1);self.assertEqual(row.bar.value(),1)
