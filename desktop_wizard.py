"""Пошаговый Qt-интерфейс: таблица → НОСИМО → сбор; сборщики остаются в MainWindow."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemDelegate, QAbstractItemView, QComboBox, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QStackedWidget,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from workbook_document import price_value
from workbook_preview import preview, apply_prices


class InlinePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.path=None;self.snapshot=None;self.pending={};self.editable=False;self.invalid=False
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        header=QHBoxLayout();self.title=QLabel('Предпросмотр таблицы')
        self.count=QLabel('');self.count.setObjectName('muted')
        header.addWidget(self.title);header.addStretch();header.addWidget(self.count);layout.addLayout(header)
        self.grid=QTableWidget();self.grid.setAccessibleName('Предпросмотр и наши цены НОСИМО')
        self.grid.setAlternatingRowColors(False);self.grid.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.grid.setEditTriggers(QAbstractItemView.DoubleClicked|QAbstractItemView.EditKeyPressed)
        self.grid.itemChanged.connect(self.changed);layout.addWidget(self.grid,1)
        footer=QHBoxLayout();self.status=QLabel('Выберите таблицу на первом шаге.');self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText);footer.addWidget(self.status,1)
        self.save_btn=QPushButton('Сохранить цены');self.save_btn.clicked.connect(self.save);self.save_btn.hide()
        footer.addWidget(self.save_btn)
        self.discard_btn=QPushButton('Отменить правки');self.discard_btn.clicked.connect(lambda:self.discard())
        self.discard_btn.hide();footer.addWidget(self.discard_btn);layout.addLayout(footer)

    def load(self,path,template='all',stores=None):
        if not self.save():return False
        if not path:
            self.snapshot=None;self.grid.clear();self.grid.setRowCount(0);return True
        try:
            data=preview(path,template,stores)
        except Exception as error:
            self.snapshot=None;self.grid.clear();self.grid.setRowCount(0)
            self.status.setText(str(error));return False
        self.path=Path(path);self.set_snapshot(data);return True

    def set_snapshot(self,data):
        self.snapshot=data;self.pending={};self.invalid=False
        self.grid.blockSignals(True);self.grid.clear()
        self.grid.setColumnCount(len(data['columns'])+2);self.grid.setRowCount(len(data['rows']))
        self.grid.setHorizontalHeaderLabels(['Артикул']+[c['name'] for c in data['columns']]+['НОСИМО'])
        for i,row in enumerate(data['rows']):
            values=[row['article']]+row['prices']+[row['baseDisplay']]
            for j,text in enumerate(values):
                item=QTableWidgetItem(text);item.setToolTip(text)
                item.setFlags(Qt.ItemIsEnabled|Qt.ItemIsSelectable)
                if j==len(values)-1 and self.editable:item.setFlags(item.flags()|Qt.ItemIsEditable)
                if j:item.setTextAlignment(Qt.AlignRight|Qt.AlignVCenter)
                if 0<j<len(values)-1 and row['lower'][j-1]:item.setForeground(QColor('#b93836'))
                self.grid.setItem(i,j,item)
            self.grid.setRowHeight(i,42)
        self.grid.resizeColumnsToContents();self.grid.horizontalHeader().setStretchLastSection(True)
        self.grid.setColumnWidth(0,max(160,self.grid.columnWidth(0)))
        self.grid.blockSignals(False)
        self.count.setText(f"{data['count']} товаров")
        self.status.setStyleSheet('');self.status.setText('Оформление файла Excel сохраняется.' if data['count'] else 'В таблице нет артикулов для мониторинга.')
        self.save_btn.setEnabled(False)
        self.discard_btn.setVisible(False)

    def set_editable(self,value):
        self.editable=value;self.save_btn.setVisible(value)
        if self.snapshot:
            self.grid.blockSignals(True)
            col=self.grid.columnCount()-1
            for i in range(self.grid.rowCount()):
                item=self.grid.item(i,col)
                if value:item.setFlags(item.flags()|Qt.ItemIsEditable)
                else:item.setFlags(item.flags()&~Qt.ItemIsEditable)
            self.grid.blockSignals(False)

    def changed(self,item):
        if not self.snapshot:return
        i=item.row();row=self.snapshot['rows'][i]
        old=self.pending.get(row['row'],row['base'])
        try:
            value=price_value(item.text())
            initial=price_value(row['base'])
            if value==initial:self.pending.pop(row['row'],None)
            else:self.pending[row['row']]='' if value is None else str(value)
            self.invalid=False;self.status.setStyleSheet('');self.status.setText('Есть несохранённые цены.' if self.pending else 'Изменений нет.')
        except ValueError as error:
            self.invalid=True;self.status.setStyleSheet('color:#b42318');self.status.setText(str(error))
            self.grid.blockSignals(True);item.setText(old);self.grid.blockSignals(False)
        self.save_btn.setEnabled(bool(self.pending))
        self.discard_btn.setVisible(bool(self.pending))

    def discard(self,confirm=True):
        if confirm and self.pending:
            choice=QMessageBox.question(self,'Отменить правки НОСИМО?',
                'Несохранённые цены будут отброшены. Существующий файл не изменится.',
                QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Cancel)
            if choice!=QMessageBox.Discard:return False
        self.pending={};self.invalid=False
        if self.snapshot:
            self.load(self.path,self.snapshot['template'],[c['key'] for c in self.snapshot['columns']])
        return True

    def save(self):
        editor=self.grid.findChild(QLineEdit)
        if editor and editor.isVisible():
            self.grid.commitData(editor);self.grid.closeEditor(editor,QAbstractItemDelegate.NoHint)
            if self.invalid:return False
        if not self.pending:return True
        try:
            data=apply_prices(self.path,self.snapshot['fingerprint'],
                [{'row':r,'value':v} for r,v in self.pending.items()],self.snapshot['template'],
                stores=[c['key'] for c in self.snapshot['columns']])
        except Exception as error:
            self.status.setStyleSheet('color:#b42318');self.status.setText(str(error));return False
        self.set_snapshot(data);self.status.setText('Цены сохранены. Резервная копия создана.');return True


class GuidedLayout:
    titles=['Выберите таблицу и источник','Проверьте наши цены','Всё готово к сбору']
    hints=['Выберите файл, шаблон и папку для результатов.',
           'Меняйте колонку НОСИМО прямо в предпросмотре. Остальные ячейки защищены.',
           'Проверьте настройки и начните сбор цен конкурентов.']

    def __init__(self,w,path_label):
        self.w=w;self.path_label=path_label;self.step=0
        root=QWidget();root.setObjectName('root');w.setCentralWidget(root)
        layout=QVBoxLayout(root);layout.setContentsMargins(28,18,28,18);layout.setSpacing(18)
        top=QHBoxLayout();brand=QLabel('Мониторинг цен');brand.setObjectName('brand');top.addWidget(brand)
        top.addStretch();self.help_btn=QPushButton('Справка');self.help_btn.clicked.connect(w.open_guide);top.addWidget(self.help_btn)
        layout.addLayout(top)
        w.header_hint=QLabel('');w.header_hint.setObjectName('caption');w.header_hint.setWordWrap(True);layout.addWidget(w.header_hint)
        self.title=QLabel(self.titles[0]);self.title.setObjectName('title');layout.addWidget(self.title)
        self.subtitle=QLabel(self.hints[0]);self.subtitle.setObjectName('muted');self.subtitle.setWordWrap(True);layout.addWidget(self.subtitle)
        steps=QHBoxLayout();self.steps=[]
        for i,name in enumerate(['Таблица','Наши цены','Сбор цен']):
            b=QPushButton(f'{i+1}  {name}');b.setObjectName('wizardStep');b.clicked.connect(lambda _,index=i:self.go(index))
            b.setAccessibleName(f'Шаг {i+1}: {name}');steps.addWidget(b);self.steps.append(b)
        layout.addLayout(steps)
        body=QHBoxLayout();body.setSpacing(24)
        self.pages=QStackedWidget();self.pages.setMinimumWidth(270);self.pages.setMaximumWidth(350)
        self.pages.addWidget(self.setup_page());self.pages.addWidget(self.prices_page());self.pages.addWidget(self.review_page())
        scroller=QScrollArea();scroller.setWidgetResizable(True);scroller.setFrameShape(QFrame.NoFrame)
        scroller.setWidget(self.pages);scroller.setMinimumWidth(285);scroller.setMaximumWidth(365);body.addWidget(scroller)
        self.preview=InlinePreview();body.addWidget(self.preview,1);layout.addLayout(body,1)
        w.progress_card=w._progress_card();layout.addWidget(w.progress_card)
        w.result_card=w._result_card();layout.addWidget(w.result_card)
        self.details_btn=QPushButton('Показать журнал сбора');self.details_btn.setCheckable(True);layout.addWidget(self.details_btn)
        self.details=QTabWidget();self.details.setMaximumHeight(165);self.details.hide()
        self.details.addTab(w._feed_card(),'Журнал')
        w.stores_card=QWidget();w.stores_grid=QGridLayout(w.stores_card);w.stores_grid.setColumnStretch(1,1)
        self.details.addTab(w.stores_card,'Магазины');layout.addWidget(self.details)
        self.details_btn.toggled.connect(self.details.setVisible)
        w.idle_card=QWidget(root);w.idle_card.hide()
        footer=QHBoxLayout();self.note=QLabel('Оформление Excel сохраняется.');self.note.setObjectName('caption')
        self.note.setWordWrap(True);footer.addWidget(self.note,1)
        self.back=QPushButton('Назад');self.back.clicked.connect(lambda:self.go(self.step-1));footer.addWidget(self.back)
        w.start_btn=QPushButton();w.start_btn.setObjectName('primary');w.start_btn.setMinimumWidth(180)
        w.start_btn.clicked.connect(self.next);footer.addWidget(w.start_btn);layout.addLayout(footer)

    def setup_page(self):
        w=self.w;page=QWidget();v=QVBoxLayout(page);v.setContentsMargins(0,0,8,0);v.setSpacing(10)
        self.section(v,'Таблица мониторинга')
        w.source_name=QLabel('Выберите .xlsx');w.source_name.setWordWrap(True);v.addWidget(w.source_name)
        w.badge=QLabel();w.badge.setObjectName('badge');v.addWidget(w.badge,0,Qt.AlignLeft)
        PathLabel=self.path_label
        w.source_dir=PathLabel();v.addWidget(w.source_dir)
        w.source_btn=QPushButton('Выбрать таблицу…');w.source_btn.clicked.connect(w.choose_source);v.addWidget(w.source_btn)
        self.section(v,'Шаблон сбора')
        w.template_picker=QComboBox();w.template_picker.setAccessibleName('Шаблон мониторинга ТВ')
        w.template_picker.addItem('samsungstore · Санкт-Петербург','tv-spb');w.template_picker.addItem('Все магазины','all')
        w.template_picker.currentIndexChanged.connect(w.change_template);v.addWidget(w.template_picker)
        self.single_source=QLabel();self.single_source.setWordWrap(True);v.addWidget(self.single_source)
        w.stores_row=QVBoxLayout();v.addLayout(w.stores_row)
        w.stores_warn=QLabel('Отметьте хотя бы один магазин');w.stores_warn.setObjectName('warn');v.addWidget(w.stores_warn)
        w.all_stores_btn=QPushButton('Все');w.all_stores_btn.clicked.connect(w.toggle_all_stores);v.addWidget(w.all_stores_btn,0,Qt.AlignLeft)
        more=QPushButton('Папка и ссылки');more.setCheckable(True);self.more=more;v.addWidget(more)
        self.extras=QWidget();extras=QVBoxLayout(self.extras);extras.setContentsMargins(0,0,0,0)
        w.target_name=QLabel();w.target_name.setWordWrap(True);extras.addWidget(w.target_name)
        w.target_hint=PathLabel();extras.addWidget(w.target_hint)
        w.root_btn=QPushButton('Выбрать папку…');w.root_btn.clicked.connect(w.choose_root);extras.addWidget(w.root_btn)
        w.links_name=QLabel();w.links_name.setWordWrap(True);extras.addWidget(w.links_name)
        w.links_dir=PathLabel();extras.addWidget(w.links_dir)
        w.links_hint=QLabel();w.links_hint.setObjectName('caption');w.links_hint.setWordWrap(True);extras.addWidget(w.links_hint)
        w.fill_btn=QPushButton('Заполнить ссылки автоматически');w.fill_btn.clicked.connect(w.fill_links);extras.addWidget(w.fill_btn)
        w.open_links_btn=QPushButton('Открыть ссылки');w.open_links_btn.clicked.connect(lambda:w.open_workbook(w.effective_links(),mode='links'));extras.addWidget(w.open_links_btn)
        v.addWidget(self.extras);self.extras.hide();more.toggled.connect(self.extras.setVisible)
        w.setup_widgets=[w.source_btn,w.root_btn,w.open_links_btn,more]
        v.addStretch();return page

    def prices_page(self):
        w=self.w;page=QWidget();v=QVBoxLayout(page);v.setContentsMargins(0,0,8,0);v.setSpacing(15)
        title=QLabel('Наши цены НОСИМО');title.setObjectName('section');v.addWidget(title)
        text=QLabel('Измените нужные цены справа. Перед переходом на следующий шаг они сохранятся с резервной копией.')
        text.setWordWrap(True);v.addWidget(text)
        w.nosimo_btn=QPushButton('Обновить с galaxystore');w.nosimo_btn.clicked.connect(w.update_nosimo);v.addWidget(w.nosimo_btn)
        w.view_source_btn=QPushButton('Открыть всю таблицу');w.view_source_btn.clicked.connect(lambda:w.open_workbook(w.source));v.addWidget(w.view_source_btn)
        text=QLabel('Цены конкурентов защищены от ручного изменения.');text.setObjectName('caption');text.setWordWrap(True);v.addWidget(text)
        v.addStretch();return page

    def review_page(self):
        w=self.w;page=QWidget();v=QVBoxLayout(page);v.setContentsMargins(0,0,8,0);v.setSpacing(16)
        self.review=QLabel();self.review.setWordWrap(True);self.review.setTextFormat(Qt.PlainText);v.addWidget(self.review)
        info=QLabel('Исходная таблица сохраняется. При ошибке сайта прежние цены остаются в результате, причина попадает в журнал.')
        info.setWordWrap(True);info.setObjectName('muted');v.addWidget(info)
        w.last_btn=QPushButton('Открыть последний результат');w.last_btn.clicked.connect(lambda:w.open_workbook(w.settings.value('lastResult')));v.addWidget(w.last_btn)
        v.addStretch();return page

    @staticmethod
    def section(layout,text):
        label=QLabel(text);label.setObjectName('section');layout.addWidget(label)

    def preview_path(self):
        w=self.w
        return (w.saved[0] if self.step==2 and w.phase in ('finished','stopped') and w.mode=='prices' and w.saved else w.source)

    def reload(self):
        return self.preview.load(self.preview_path(),self.w.active_template(),self.w.selected_stores())

    def go(self,index):
        w=self.w
        if w.busy() or index<0 or index>2:return False
        if index>0 and not(w.can_start() and w.selected_stores() and self.preview.snapshot and self.preview.snapshot['count']):return False
        if not self.preview.save():return False
        self.step=index
        if self.preview.path != (Path(self.preview_path()) if self.preview_path() else None):
            self.reload()
        w.refresh();return True

    def next(self):
        if self.w.busy():self.w.stop();return
        if self.step<2:self.go(self.step+1)
        else:
            if self.preview.save():self.w.start_or_stop()

    def sync(self):
        w=self.w;busy=w.busy()
        if busy:self.step=2
        w.progress_card.setVisible(self.step==2 and w.phase!="idle" and (w.total>0 or busy))
        w.result_card.setVisible(self.step==2 and w.phase in ("finished","stopped","failed"))
        self.pages.setCurrentIndex(self.step)
        self.title.setText('Собираем цены' if busy else self.titles[self.step])
        self.subtitle.setText(self.hints[self.step])
        self.preview.set_editable(self.step==1 and not busy)
        single=w.table_type=='ТВ' and w.template_picker.count()==1
        self.single_source.setVisible(single)
        self.single_source.setText(w.template_picker.currentText())
        w.template_picker.setVisible(w.table_type=='ТВ' and not single)
        w.all_stores_btn.setVisible(len(w.store_checks)>1)
        for checkbox in w.store_checks.values():checkbox.setVisible(len(w.store_checks)>1)
        ready=w.can_start() and bool(w.selected_stores()) and bool(self.preview.snapshot and self.preview.snapshot['count'])
        for i,b in enumerate(self.steps):
            b.setProperty('active',i==self.step);b.setEnabled(not busy and(i==0 or ready))
            b.style().unpolish(b);b.style().polish(b)
        self.back.setEnabled(self.step>0 and not busy)
        w.start_btn.setText('Останавливаю…' if w.phase=='stopping' else 'Остановить' if busy else
                            ['Далее: наши цены','Далее: сбор цен','Собрать цены'][self.step])
        w.start_btn.setEnabled((busy and w.phase!='stopping') or (not busy and ready))
        self.review.setText('Таблица\n'+(w.source.name if w.source else 'Не выбрана')+'\n\nИсточник\n'+
            ('samsungstore · Санкт-Петербург' if w.active_template()=='tv-spb' else ', '.join(w.selected_stores()))+
            '\n\nРезультат\n'+(str(w.root) if w.root else 'Выберите папку'))
        self.details_btn.setVisible(self.step==2 and (busy or bool(w.stores)))
        self.details.setVisible(self.details_btn.isVisible() and self.details_btn.isChecked())
        if not w.root:self.more.setChecked(True)
        self.note.setText('Оформление Excel сохраняется.' if ready else 'Выберите таблицу, папку и хотя бы один магазин.')
